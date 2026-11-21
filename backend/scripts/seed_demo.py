import json,random
from datetime import date,datetime,timedelta
from pathlib import Path
from sqlalchemy import select,func
from src.database import Base,engine,Session
from src.models import User,Hive,Visit
from src.auth import hash_password
from src.resource_models import FeedLot,FeedIssue,QueenObservation
from src.season_models import InsulationLot
from src.backtest_models import FieldLabel

ROUND1_AT=datetime(2026,11,17,9,0)
ROUND2_AT=datetime(2026,11,18,15,30)
ROUND2_WEAK={7,14,22,31,39,47,55,62,70,75}

def round2_values(rng,weak):
    if weak:
        return {'weight_kg':round(rng.uniform(15.5,19),2),'temperature':round(rng.uniform(25,29),2),
                'activity':round(rng.uniform(4,14),1),'feed_left':round(rng.uniform(.1,.5),2)}
    return {'weight_kg':round(rng.uniform(25,34),2),'temperature':round(rng.uniform(32,35),2),
            'activity':round(rng.uniform(38,86),1),'feed_left':round(rng.uniform(1.5,3.8),2)}

def seed():
    Base.metadata.create_all(engine)
    with Session() as db:
        for role in ['admin','beekeeper','viewer']:
            email=role+'@shanjing.test'
            if not db.scalar(select(User).where(User.email==email)):db.add(User(email=email,password=hash_password('Hive2026!'),role=role))
        for i in range(1,81):
            code=f'H-{i:03}'
            if not db.scalar(select(Hive).where(Hive.code==code)):db.add(Hive(code=code,site='山荆东坡' if i<=40 else '山荆林缘',queen_present=i not in [31,62],colony_frames=4 if i in [31,47,62,75] else 8,care_state='observe'))
        db.flush();hives=db.scalars(select(Hive).order_by(Hive.id)).all();reference=json.loads((Path(__file__).resolve().parents[1]/'fixtures/winter_reference.json').read_text())
        round1=[]
        for i,values in enumerate(reference):
            code=f'V-1117-{i+1:03}';hive=hives[i%80]
            visit=db.scalar(select(Visit).where(Visit.code==code))
            if visit is None:
                visit=Visit(code=code,hive_id=hive.id,queen_seen=hive.code not in ['H-031','H-062'],colony_frames=4 if hive.code in ['H-031','H-047','H-062','H-075'] else 8,recorded_at=ROUND1_AT,**values)
                db.add(visit);db.flush()
            round1.append(visit)
        rng=random.Random(42);round2=[]
        for i,hive in enumerate(hives):
            code=f'V-1118-{i+1:03}'
            visit=db.scalar(select(Visit).where(Visit.code==code))
            if visit is None:
                weak=(i+1) in ROUND2_WEAK
                frames=4 if weak else 8
                visit=Visit(code=code,hive_id=hive.id,queen_seen=not (weak and (i+1) in [31,62]),
                            colony_frames=frames,recorded_at=ROUND2_AT,**round2_values(rng,weak))
                db.add(visit);db.flush()
            round2.append(visit)
        # 现场强弱在出分前登记；弱群口径=蜂量不足5框。V-1117-077 故意不登记，演示未登记单列
        for visit in round1+round2:
            if visit.code=='V-1117-077':continue
            if not db.scalar(select(FieldLabel).where(FieldLabel.visit_id==visit.id)):
                db.add(FieldLabel(visit_id=visit.id,is_weak=visit.colony_frames<5,registered_by='beekeeper@shanjing.test'))
        for code,kg,expiry,state in [('FD-202611-A',30,date(2027,11,30),'active'),('FD-HOLD',8,date(2027,5,1),'quarantine'),('FD-EXPIRED',5,date(2026,1,1),'active')]:
            if not db.scalar(select(FeedLot).where(FeedLot.code==code)):db.add(FeedLot(code=code,received_kg=kg,available_kg=kg,expires_on=expiry,state=state))
        if not db.scalar(select(InsulationLot).where(InsulationLot.code=='IN-2026-WINTER')):db.add(InsulationLot(code='IN-2026-WINTER',available_units=120))
        db.commit();print({key:db.scalar(select(func.count()).select_from(model)) for key,model in [('users',User),('hives',Hive),('visits',Visit),('field_labels',FieldLabel)]})
if __name__=='__main__':seed()
