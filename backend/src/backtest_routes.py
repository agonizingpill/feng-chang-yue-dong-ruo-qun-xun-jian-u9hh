import os
import redis
from fastapi import APIRouter,Depends
from sqlalchemy import select
from .database import session
from .auth import current,editor
from .models import Hive,Visit
from .backtest_models import FieldLabel,BacktestRun,BacktestReport
from .backtest_schemas import LabelInput,BacktestInput,BacktestRetry
from . import backtest_service
router=APIRouter()
queue=redis.Redis.from_url(os.getenv('REDIS_URL','redis://redis:6379/0'),decode_responses=True)

@router.get('/field-labels')
def labels(user=Depends(current),db=Depends(session)):
    return db.scalars(select(FieldLabel).order_by(FieldLabel.id.desc())).all()

@router.get('/field-labels/unregistered')
def unregistered(user=Depends(current),db=Depends(session)):
    """未登记现场强弱的巡检单列，回测样本不包含它们。"""
    registered={row.visit_id for row in db.scalars(select(FieldLabel)).all()}
    rows=db.scalars(select(Visit).where(~Visit.id.in_(registered)).order_by(Visit.id)).all()
    return [{'visit_id':v.id,'code':v.code,'hive_id':v.hive_id,
             'site':db.get(Hive,v.hive_id).site,'status':v.status} for v in rows]

@router.post('/field-labels')
def register(body:LabelInput,user=Depends(editor),db=Depends(session)):
    return backtest_service.register_label(db,body,user)

@router.get('/backtests')
def runs(user=Depends(current),db=Depends(session)):
    out=[]
    for run in db.scalars(select(BacktestRun).order_by(BacktestRun.id.desc())).all():
        report=db.scalar(select(BacktestReport).where(BacktestReport.run_id==run.id))
        out.append({'run':run,'report':report})
    return out

@router.post('/backtests')
def start(body:BacktestInput,user=Depends(editor),db=Depends(session)):
    return backtest_service.create_run(db,body,user,queue)

@router.post('/backtests/{key}/retry')
def retry(key:int,body:BacktestRetry,user=Depends(editor),db=Depends(session)):
    return backtest_service.retry_run(db,key,user,queue)
