from datetime import datetime
from sqlalchemy import String,Float,Boolean,ForeignKey,JSON,UniqueConstraint,DateTime,func
from sqlalchemy.orm import Mapped,mapped_column
from .database import Base

class FieldLabel(Base):
    """蜂师出分前在现场登记的强弱判定；未登记的巡检不进入回测样本。"""
    __tablename__='field_labels'
    id:Mapped[int]=mapped_column(primary_key=True)
    visit_id:Mapped[int]=mapped_column(ForeignKey('visits.id'),unique=True)
    is_weak:Mapped[bool]=mapped_column(Boolean)
    registered_by:Mapped[str]=mapped_column(String(120))
    registered_at:Mapped[datetime]=mapped_column(DateTime,server_default=func.now())
    revised_by:Mapped[str]=mapped_column(String(120),default='')
    revised_at:Mapped[datetime|None]=mapped_column(DateTime,nullable=True)
    revision_note:Mapped[str]=mapped_column(String(300),default='')

class BacktestRun(Base):
    """一次阈值回测；样本快照在创建时冻结，中断重试沿用同一行与同一快照。"""
    __tablename__='backtest_runs'
    id:Mapped[int]=mapped_column(primary_key=True)
    code:Mapped[str]=mapped_column(String(40),unique=True)
    early_ratio:Mapped[float]=mapped_column(Float)
    false_positive_cap:Mapped[int]=mapped_column()
    sample_snapshot:Mapped[dict]=mapped_column(JSON)
    state:Mapped[str]=mapped_column(String(20),default='queued')
    created_by:Mapped[str]=mapped_column(String(120))
    created_at:Mapped[datetime]=mapped_column(DateTime,server_default=func.now())
    started_at:Mapped[datetime|None]=mapped_column(DateTime,nullable=True)
    finished_at:Mapped[datetime|None]=mapped_column(DateTime,nullable=True)
    error:Mapped[str]=mapped_column(String(400),default='')
    voided_by:Mapped[str]=mapped_column(String(120),default='')
    voided_at:Mapped[datetime|None]=mapped_column(DateTime,nullable=True)
    void_reason:Mapped[str]=mapped_column(String(300),default='')
    attempts:Mapped[int]=mapped_column(default=0)

class BacktestReport(Base):
    """不可变回测报告：一行对应一次回测，唯一约束保证重试不重复出报告。"""
    __tablename__='backtest_reports'
    __table_args__=(UniqueConstraint('run_id',name='uq_backtest_report_run'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    run_id:Mapped[int]=mapped_column(ForeignKey('backtest_runs.id'))
    baseline_threshold:Mapped[float]=mapped_column(Float)
    trial_threshold:Mapped[float]=mapped_column(Float)
    payload:Mapped[dict]=mapped_column(JSON)
    issued_by:Mapped[str]=mapped_column(String(120))
    issued_at:Mapped[datetime]=mapped_column(DateTime,server_default=func.now())
