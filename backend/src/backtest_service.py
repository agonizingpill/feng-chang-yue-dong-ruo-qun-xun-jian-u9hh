import uuid
from datetime import datetime
from sqlalchemy import select
from fastapi import HTTPException
from .models import Hive,Visit
from .backtest_models import FieldLabel,BacktestRun,BacktestReport
from .screen_model import reference_model
from .yard_service import require,audit

def _score(visit):
    model,evidence=reference_model()
    return float(model.score_samples([[visit.weight_kg,visit.temperature,visit.activity,visit.feed_left]])[0]),evidence['threshold']

def confusion(samples,threshold):
    """弱群为正类；score<threshold 预测为弱（异常）。"""
    tp=fp=tn=fn=0
    for row in samples:
        flagged=row['score']<threshold
        if flagged and row['is_weak']:tp+=1
        elif flagged and not row['is_weak']:fp+=1
        elif not flagged and not row['is_weak']:tn+=1
        else:fn+=1
    return {'tp':tp,'fp':fp,'tn':tn,'fn':fn}

def site_metrics(samples,threshold,sites):
    out={}
    for site in sites:
        part=[r for r in samples if r['site']==site]
        out[site]={**confusion(part,threshold),'total':len(part),'weak':sum(1 for r in part if r['is_weak'])}
    return out

def choose_trial_threshold(early,cap,baseline):
    """候选阈值取早期段实际分值（保证每个候选都对应一次判定变化），
    选误报不超上限中漏报最少；漏报并列取误报更少，再并列取阈值更高（少打扰）。"""
    candidates=sorted({round(r['score'],6) for r in early}|{round(baseline,6)},reverse=True)
    eligible=[]
    for threshold in candidates:
        m=confusion(early,threshold)
        if m['fp']<=cap:eligible.append((m['fn'],m['fp'],-threshold,threshold))
    if not eligible:
        raise HTTPException(409,'给定误报上限下没有可行阈值，请放宽上限后再回测')
    return sorted(eligible)[0][3]

def build_snapshot(db,early_ratio):
    """只取已登记现场强弱的巡检；按蜂箱分层切分，同箱样本整体落一段，绝不跨段。"""
    labels=db.scalars(select(FieldLabel)).all()
    if not labels:raise HTTPException(409,'还没有现场强弱登记，回测需要蜂师先登记标签')
    by_hive={}
    for label in labels:
        visit=db.get(Visit,label.visit_id)
        hive=db.get(Hive,visit.hive_id)
        score,_=_score(visit)
        by_hive.setdefault(hive.id,[]).append({
            'visit_id':visit.id,'hive_id':hive.id,'site':hive.site,'code':visit.code,
            'is_weak':label.is_weak,'score':score,
        })
    early,late=[],[]
    # 按蜂场分层切分：每个场内按 early_ratio 分箱，保证两场在早期/后期都有样本；同一蜂箱整体落一段
    site_hives={}
    for hive_id,rows in by_hive.items():
        site=rows[0]['site']
        site_hives.setdefault(site,[]).append(hive_id)
    for site in sorted(site_hives):
        hive_ids=sorted(site_hives[site])
        target_early=round(len(hive_ids)*early_ratio)
        for hive_id in hive_ids[:target_early]:
            early.extend(sorted(by_hive[hive_id],key=lambda r:r['visit_id']))
        for hive_id in hive_ids[target_early:]:
            late.extend(sorted(by_hive[hive_id],key=lambda r:r['visit_id']))
    if not early or not late:raise HTTPException(409,'早期/后期样本都不能为空，请调整切分比例或补登记')
    if {r['hive_id'] for r in early}&{r['hive_id'] for r in late}:
        raise HTTPException(500,'同箱样本跨段，回测切分被拒绝')
    sites=sorted({r['site'] for r in early}|{r['site'] for r in late})
    return {'sites':sites,'early':early,'late':late,'label_count':len(labels),'hive_count':len(by_hive)}

def create_run(db,body,user,queue):
    snapshot=build_snapshot(db,body.early_ratio)
    run=BacktestRun(code='BT-'+uuid.uuid4().hex[:10],early_ratio=body.early_ratio,
                    false_positive_cap=body.false_positive_cap,sample_snapshot=snapshot,
                    state='queued',created_by=user.email,attempts=0)
    db.add(run);audit(db,user,f'发起阈值回测 {run.code} 误报上限 {body.false_positive_cap}')
    db.commit()
    queue.rpush('apiary:backtests',run.code)
    return run

def register_label(db,body,user):
    """出分前登记现场强弱；同巡检再提交即更正。更正先办：在途回测一律作废，已出报告保留。"""
    visit=require(db,Visit,body.visit_id,lock=True)
    label=db.scalar(select(FieldLabel).where(FieldLabel.visit_id==visit.id).with_for_update())
    active=db.scalars(select(BacktestRun).where(
        BacktestRun.state.in_(['queued','running','failed'])).with_for_update()).all()
    for run in active:
        ids={r['visit_id'] for seg in ('early','late') for r in run.sample_snapshot[seg]}
        if visit.id in ids:
            run.state='voided';run.voided_by=user.email;run.voided_at=datetime.now()
            run.void_reason=('现场强弱更正：'+body.note) if body.note else '现场强弱登记更正，原样本作废'
    now=datetime.now()
    if label is None:
        label=FieldLabel(visit_id=visit.id,is_weak=body.strength=='weak',registered_by=user.email,registered_at=now)
        db.add(label);audit(db,user,f'登记现场{ "弱" if label.is_weak else "强" }群 {visit.code}')
    else:
        old='弱' if label.is_weak else '强'
        label.is_weak=body.strength=='weak';label.revised_by=user.email;label.revised_at=now
        label.revision_note=body.note
        audit(db,user,f'更正现场判定 {visit.code} {old}→{ "弱" if label.is_weak else "强" }，在途回测作废')
    db.commit();return label

def retry_run(db,key,user,queue):
    run=require(db,BacktestRun,key,lock=True)
    if run.state=='done':raise HTTPException(409,'报告已出具，无需重试')
    if run.state=='voided':raise HTTPException(409,'该回测已随现场更正作废，请按新样本重新发起')
    if run.state in ('queued','running'):raise HTTPException(409,'回测仍在进行，请等待结果或稍后查看恢复情况')
    run.state='queued';run.error='';db.commit()
    audit(db,user,f'重试回测 {run.code}，沿用原样本快照')
    queue.rpush('apiary:backtests',run.code)
    return run
