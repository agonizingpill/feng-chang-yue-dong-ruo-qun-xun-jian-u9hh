import os,json,traceback
from datetime import datetime
from pathlib import Path
from sqlalchemy import select
from .database import Session
from .backtest_models import BacktestRun,BacktestReport
from .backtest_service import choose_trial_threshold,confusion,site_metrics
from .screen_model import reference_model

def _payload(run):
    snap=run.sample_snapshot;early=snap['early'];late=snap['late'];sites=snap['sites']
    baseline=float(reference_model()[1]['threshold'])
    trial=choose_trial_threshold(early,run.false_positive_cap,baseline)
    return {
        'code':run.code,'sites':sites,
        'early_ratio':run.early_ratio,'false_positive_cap':run.false_positive_cap,
        'baseline_threshold':baseline,'trial_threshold':trial,
        'sample':{'label_count':snap['label_count'],'hive_count':snap['hive_count'],
                  'early_total':len(early),'late_total':len(late)},
        'early':{
            'baseline':confusion(early,baseline),'trial':confusion(early,trial),
            'sites':{'baseline':site_metrics(early,baseline,sites),'trial':site_metrics(early,trial,sites)}},
        'late':{
            'baseline':confusion(late,baseline),'trial':confusion(late,trial),
            'sites':{'baseline':site_metrics(late,baseline,sites),'trial':site_metrics(late,trial,sites)}},
        'candidate_rule':'误报不超过上限的候选中漏报最少；漏报并列取误报更少，再并列取阈值更高',
    }

def execute_backtest(code):
    """从数据库行恢复执行：样本快照是唯一事实来源，重试不重建样本、不重复出报告。"""
    with Session() as db:
        run=db.scalar(select(BacktestRun).where(BacktestRun.code==code).with_for_update())
        if run is None or run.state=='voided' or run.state=='done':return
        existing=db.scalar(select(BacktestReport).where(BacktestReport.run_id==run.id))
        if existing is not None:
            run.state='done';run.finished_at=run.finished_at or datetime.now();db.commit();return
        run.state='running';run.started_at=run.started_at or datetime.now()
        run.attempts+=1;db.commit()
    try:
        with Session() as db:
            run=db.scalar(select(BacktestRun).where(BacktestRun.code==code).with_for_update())
            if run.state=='voided':return
            payload=_payload(run)
            report=BacktestReport(run_id=run.id,baseline_threshold=payload['baseline_threshold'],
                                  trial_threshold=payload['trial_threshold'],payload=payload,
                                  issued_by=run.created_by)
            db.add(report)
            run.state='done';run.finished_at=datetime.now();run.error='';db.commit()
            result={'status':'done','code':code,'report_id':report.id,'payload':payload}
        Path(os.getenv('ARTIFACTS_DIR','/artifacts')).mkdir(exist_ok=True)
        Path(os.path.join(os.getenv('ARTIFACTS_DIR','/artifacts'),f'backtest-{code}.json')).write_text(json.dumps(result,ensure_ascii=False))
    except Exception as error:
        traceback.print_exc()
        with Session() as db:
            run=db.scalar(select(BacktestRun).where(BacktestRun.code==code).with_for_update())
            if run is not None and run.state!='voided':
                run.state='failed';run.error=str(error)[:400];db.commit()

def recover_stale(queue):
    """worker 启动/周期恢复：排队或运行中的批次重新入队，从原样本继续，不产生重复报告。"""
    with Session() as db:
        rows=db.scalars(select(BacktestRun).where(BacktestRun.state.in_(['queued','running']))).all()
        for run in rows:queue.rpush('apiary:backtests',run.code)
        return [r.code for r in rows]
