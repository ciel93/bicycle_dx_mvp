from fastapi import FastAPI, Depends, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, DateTime, or_
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
import os
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from enum import Enum
from pydantic import BaseModel, Field

# 日本時間（JST = UTC+9）の定義
JST = timezone(timedelta(hours=9))

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:password@db:5432/bicycle_dx")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ── Enum 定義 ──
class ReceiptStatus(str, Enum):
    received = "受付完了"
    estimating = "見積中"
    repairing = "整備中"
    waiting_payment = "決済待ち"
    completed = "引渡完了"

class LaneLocation(str, Enum):
    waiting_repair = "修理待ちエリア"
    repair_pit = "作業場（ピット）"
    waiting_delivery = "引き渡し待機"
    backyard = "バックヤード倉庫"

class JobCategory(str, Enum):
    repair = "一般修理・メンテナンス"
    new_bike_prep = "新車おろし・納車整備"

class StaffMember(str, Enum):
    ciel = "シエル（店長）"
    lorelei = "ローレライ（スタッフ）"
    saki = "サキ（スタッフ）"
    other = "その他スタッフ"

class WorkType(str, Enum):
    puncture = "パンク修理"
    tire_replacement = "タイヤ・チューブ交換"
    brake_adjustment = "ブレーキ調整・交換"
    general_inspection = "定期点検・オーバーホール"
    new_assembly = "新車組み立て（納車整備）"
    other = "その他"

class BicycleMaker(str, Enum):
    bridgestone = "ブリヂストン (BRIDGESTONE)"
    panasonic = "パナソニック (Panasonic)"
    yamaha = "ヤマハ (YAMAHA)"
    giant = "ジャイアント (GIANT)"
    miyata = "ミヤタ (MIYATA)"
    other = "その他"

class BicycleColor(str, Enum):
    black = "ブラック"
    silver = "シルバー"
    white = "ホワイト"
    red = "レッド"
    blue = "ブルー"
    brown = "ブラウン"
    green = "グリーン"
    other = "その他"


# ── DB Model ──
class Receipt(Base):
    __tablename__ = "receipts"
    id = Column(Integer, primary_key=True, index=True)
    customer_name = Column(String, index=True, nullable=False)
    contact = Column(String, nullable=False)
    job_category = Column(String, index=True, nullable=False)
    receptionist = Column(String, nullable=False)
    mechanic = Column(String, nullable=True)
    maker = Column(String, nullable=False)
    maker_other = Column(String, nullable=True)
    model = Column(String, nullable=False)
    color = Column(String, nullable=False)
    work_type = Column(String, nullable=False)
    work_type_other = Column(String, nullable=True)
    status = Column(String, index=True, nullable=False)
    created_at = Column(DateTime, nullable=False)
    due_date = Column(DateTime, nullable=True)
    lane_id = Column(String, index=True, nullable=False)

Base.metadata.create_all(bind=engine)


# ── Pydantic Schemas ──
class ReceiptCreate(BaseModel):
    customer_name: str = Field("山田 太郎", description="顧客名")
    contact: str = Field("090-1234-5678", description="連絡先")
    job_category: JobCategory = Field(JobCategory.repair, description="案件区分")
    receptionist: StaffMember = Field(StaffMember.ciel, description="受付担当者")
    mechanic: Optional[StaffMember] = Field(StaffMember.lorelei, description="作業担当者")
    maker: BicycleMaker = Field(BicycleMaker.bridgestone, description="メーカー")
    maker_other: Optional[str] = Field(None, description="メーカー『その他』の詳細")
    model: str = Field("アルベルト", description="車種名")
    color: BicycleColor = Field(BicycleColor.black, description="カラー")
    work_type: WorkType = Field(WorkType.puncture, description="主な作業種別")
    work_type_other: Optional[str] = Field(None, description="作業『その他』の詳細")
    status: ReceiptStatus = Field(ReceiptStatus.received, description="ステータス")
    lane_id: LaneLocation = Field(LaneLocation.waiting_repair, description="配置レーン")
    
    due_days_offset: Optional[int] = Field(0, description="納期の日数オフセット（0=当日, 1=明日... None=要確認）")
    due_hour: int = Field(15, ge=0, le=23, description="納期の時間（時）")
    due_minute: int = Field(0, ge=0, le=59, description="納期の時間（分）")

class ReceiptUpdate(BaseModel):
    job_category: Optional[JobCategory] = None
    receptionist: Optional[StaffMember] = None
    mechanic: Optional[StaffMember] = None
    status: Optional[ReceiptStatus] = None
    lane_id: Optional[LaneLocation] = None
    
    due_days_offset: Optional[int] = Field(None, description="納期の日数を変更")
    due_hour: Optional[int] = Field(None, ge=0, le=23, description="納期の時間を変更")
    due_minute: Optional[int] = Field(None, ge=0, le=59, description="納期の分を変更")
    is_pending_contact: Optional[bool] = Field(False, description="Trueにすると納期を『要確認（Null）』に変更")

class ReceiptResponse(BaseModel):
    id: int
    customer_name: str
    contact: str
    job_category: str
    receptionist: str
    mechanic: Optional[str]
    maker: str
    maker_other: Optional[str]
    model: str
    color: str
    work_type: str
    work_type_other: Optional[str]
    status: str
    created_at: datetime
    due_date: Optional[datetime]
    lane_id: str

    class Config:
        from_attributes = True


# ── FastAPI App ──
app = FastAPI(title="Bicycle DX API", version="2.0.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.post("/receipts/", response_model=ReceiptResponse, status_code=status.HTTP_201_CREATED)
def create_receipt(
    payload: ReceiptCreate,
    db: Session = Depends(get_db)
):
    now_jst = datetime.now(JST).replace(tzinfo=None)
    
    calculated_due_date = None
    if payload.due_days_offset is not None:
        target_date = datetime.now(JST) + timedelta(days=payload.due_days_offset)
        calculated_due_date = target_date.replace(
            hour=payload.due_hour,
            minute=payload.due_minute,
            second=0,
            microsecond=0
        ).replace(tzinfo=None)

    db_receipt = Receipt(
        customer_name=payload.customer_name,
        contact=payload.contact,
        job_category=payload.job_category.value,
        receptionist=payload.receptionist.value,
        mechanic=payload.mechanic.value if payload.mechanic else None,
        maker=payload.maker.value,
        maker_other=payload.maker_other,
        model=payload.model,
        color=payload.color.value,
        work_type=payload.work_type.value,
        work_type_other=payload.work_type_other,
        status=payload.status.value,
        created_at=now_jst,
        due_date=calculated_due_date,
        lane_id=payload.lane_id.value
    )
    
    try:
        db.add(db_receipt)
        db.commit()
        db.refresh(db_receipt)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"データベース保存エラー: {str(e)}")
        
    return db_receipt


@app.get("/receipts/", response_model=List[ReceiptResponse])
def read_receipts(
    job_category: Optional[JobCategory] = Query(None, description="案件区分で絞り込み"),
    status: Optional[ReceiptStatus] = Query(None, description="ステータスで絞り込み"),
    lane_id: Optional[LaneLocation] = Query(None, description="レーンで絞り込み"),
    mechanic: Optional[StaffMember] = Query(None, description="作業担当者で絞り込み"),
    keyword: Optional[str] = Query(None, description="あいまい検索"),
    limit: int = Query(50, ge=1, le=100, description="取得上限件数"),
    offset: int = Query(0, ge=0, description="スキップ件数"),
    db: Session = Depends(get_db)
):
    query = db.query(Receipt)
    if job_category:
        query = query.filter(Receipt.job_category == job_category.value)
    if status:
        query = query.filter(Receipt.status == status.value)
    if lane_id:
        query = query.filter(Receipt.lane_id == lane_id.value)
    if mechanic:
        query = query.filter(Receipt.mechanic == mechanic.value)
    if keyword:
        search_pattern = f"%{keyword}%"
        query = query.filter(
            or_(
                Receipt.customer_name.ilike(search_pattern),
                Receipt.maker.ilike(search_pattern),
                Receipt.maker_other.ilike(search_pattern),
                Receipt.model.ilike(search_pattern),
                Receipt.work_type_other.ilike(search_pattern)
            )
        )
    return query.offset(offset).limit(limit).all()


@app.patch("/receipts/{receipt_id}", response_model=ReceiptResponse)
def update_receipt(
    receipt_id: int,
    payload: ReceiptUpdate,
    db: Session = Depends(get_db)
):
    db_item = db.query(Receipt).filter(Receipt.id == receipt_id).first()
    if not db_item:
        raise HTTPException(status_code=404, detail="指定された受付レコードが見つかりませんわ")
    
    if payload.job_category is not None:
        db_item.job_category = payload.job_category.value
    if payload.receptionist is not None:
        db_item.receptionist = payload.receptionist.value
    if payload.mechanic is not None:
        db_item.mechanic = payload.mechanic.value
    if payload.status is not None:
        db_item.status = payload.status.value
    if payload.lane_id is not None:
        db_item.lane_id = payload.lane_id.value
        
    # ── 【修正】納期関連のパラメータ指定がある場合のみ更新を判定 ──
    has_due_update = (
        payload.is_pending_contact
        or payload.due_days_offset is not None
        or payload.due_hour is not None
        or payload.due_minute is not None
    )

    if has_due_update:
        if payload.is_pending_contact:
            db_item.due_date = None
        else:
            base_due = db_item.due_date if db_item.due_date else datetime.now(JST).replace(tzinfo=None)
            
            if payload.due_days_offset is not None:
                base_due = (datetime.now(JST) + timedelta(days=payload.due_days_offset)).replace(tzinfo=None)
                
            new_hour = payload.due_hour if payload.due_hour is not None else base_due.hour
            new_minute = payload.due_minute if payload.due_minute is not None else base_due.minute
            
            db_item.due_date = base_due.replace(hour=new_hour, minute=new_minute, second=0, microsecond=0)
            
    try:
        db.commit()
        db.refresh(db_item)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"データベース更新エラー: {str(e)}")

    return db_item