import os
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from enum import Enum

from fastapi import FastAPI, Depends, HTTPException, Query, status, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, or_, asc, desc, nullslast, nullsfirst
from sqlalchemy.orm import sessionmaker, Session, declarative_base
from pydantic import BaseModel, Field

# 日本時間（JST = UTC+9）の定義
JST = timezone(timedelta(hours=9))

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("【構成エラー】環境変数 DATABASE_URL が設定されていません。")

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
    derailleur_adjustment = "変速調整（ディレイラー）"
    cable_external = "ワイヤー交換（外通し）"
    cable_internal = "ワイヤー交換（フレーム内装）"
    general_inspection = "定期点検・オーバーホール"
    new_assembly = "新車組み立て（納車整備）"
    other = "その他"

class PaymentStatus(str, Enum):
    unpaid = "未決済"
    paid = "決済完了"
    refunded = "返金済み"

class PaymentMethod(str, Enum):
    amazon_pay = "Amazon Pay"
    store_cash = "店頭現金"
    store_credit_card = "店頭クレジットカード"
    store_qr = "店頭QR決済（PayPay等）"

DEFAULT_DURATION_MAP = {
    WorkType.puncture: 15,
    WorkType.brake_adjustment: 20,
    WorkType.derailleur_adjustment: 15,
    WorkType.cable_external: 20,
    WorkType.cable_internal: 45,
    WorkType.tire_replacement: 30,
    WorkType.new_assembly: 60,
    WorkType.general_inspection: None,
    WorkType.other: None,
}

class SortField(str, Enum):
    due_date = "due_date"
    scheduled_start_at = "scheduled_start_at"
    estimated_duration = "estimated_duration"
    created_at = "created_at"
    id = "id"

class SortOrder(str, Enum):
    asc = "asc"
    desc = "desc"

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
    tracking_token = Column(String, unique=True, index=True, nullable=False)
    
    customer_name = Column(String, index=True, nullable=False)
    contact = Column(String, index=True, nullable=False)
    job_category = Column(String, index=True, nullable=False)
    receptionist = Column(String, nullable=False)
    mechanic = Column(String, index=True, nullable=True)
    maker = Column(String, index=True, nullable=False)
    maker_other = Column(String, nullable=True)
    model = Column(String, index=True, nullable=False)
    color = Column(String, nullable=False)
    work_type = Column(String, nullable=False)
    work_type_other = Column(String, nullable=True)
    status = Column(String, index=True, nullable=False)
    created_at = Column(DateTime, index=True, nullable=False)
    due_date = Column(DateTime, index=True, nullable=True)
    lane_id = Column(String, index=True, nullable=False)
    
    # スケジュール・工数管理
    scheduled_start_at = Column(DateTime, index=True, nullable=True)
    estimated_duration = Column(Integer, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # 完了通知
    notification_sent_at = Column(DateTime, nullable=True)

    # 料金管理
    base_fee = Column(Integer, nullable=False, default=0)
    parts_fee = Column(Integer, nullable=False, default=0)
    additional_fee = Column(Integer, nullable=False, default=0)
    total_fee = Column(Integer, nullable=False, default=0)

    # 決済管理
    payment_status = Column(String, nullable=False, default=PaymentStatus.unpaid.value)
    payment_method = Column(String, nullable=True)
    payment_transaction_id = Column(String, nullable=True)
    paid_at = Column(DateTime, nullable=True)

Base.metadata.create_all(bind=engine)


# ── Pydantic Schemas ──
class ReceiptCreate(BaseModel):
    customer_name: str = Field("山田 太郎", description="顧客名")
    contact: str = Field("090-1234-5678", description="連絡先")
    job_category: JobCategory = Field(JobCategory.repair, description="案件区分")
    receptionist: StaffMember = Field(StaffMember.ciel, description="受付担当者")
    mechanic: Optional[StaffMember] = Field(StaffMember.lorelei, description="作業担当者")
    maker: BicycleMaker = Field(BicycleMaker.bridgestone, description="メーカー")
    maker_other: Optional[str] = Field(None)
    model: str = Field("アルベルト", description="車種名")
    color: BicycleColor = Field(BicycleColor.black, description="カラー")
    work_type: WorkType = Field(WorkType.puncture, description="主な作業種別")
    work_type_other: Optional[str] = Field(None)
    status: ReceiptStatus = Field(ReceiptStatus.received)
    lane_id: LaneLocation = Field(LaneLocation.waiting_repair)
    
    due_days_offset: Optional[int] = Field(0)
    due_hour: int = Field(15, ge=0, le=23)
    due_minute: int = Field(0, ge=0, le=59)
    
    scheduled_start_days_offset: Optional[int] = Field(None)
    scheduled_start_hour: Optional[int] = Field(None, ge=0, le=23)
    scheduled_start_minute: Optional[int] = Field(0, ge=0, le=59)
    estimated_duration: Optional[int] = Field(None, ge=1)

    # 料金初期値
    base_fee: int = Field(0, ge=0, description="基本工賃")
    parts_fee: int = Field(0, ge=0, description="部品代")
    additional_fee: int = Field(0, ge=0, description="追加費用")

class ReceiptUpdate(BaseModel):
    customer_name: Optional[str] = None
    contact: Optional[str] = None
    job_category: Optional[JobCategory] = None
    receptionist: Optional[StaffMember] = None
    mechanic: Optional[StaffMember] = None
    status: Optional[ReceiptStatus] = None
    lane_id: Optional[LaneLocation] = None
    maker: Optional[BicycleMaker] = None
    maker_other: Optional[str] = None
    model: Optional[str] = None
    color: Optional[BicycleColor] = None
    work_type: Optional[WorkType] = None
    work_type_other: Optional[str] = None
    
    due_days_offset: Optional[int] = None
    due_hour: Optional[int] = Field(None, ge=0, le=23)
    due_minute: Optional[int] = Field(None, ge=0, le=59)
    is_pending_contact: Optional[bool] = None
    
    scheduled_start_days_offset: Optional[int] = None
    scheduled_start_hour: Optional[int] = Field(None, ge=0, le=23)
    scheduled_start_minute: Optional[int] = Field(None, ge=0, le=59)
    clear_scheduled_start: Optional[bool] = None
    estimated_duration: Optional[int] = Field(None, ge=1)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # 料金更新
    base_fee: Optional[int] = Field(None, ge=0)
    parts_fee: Optional[int] = Field(None, ge=0)
    additional_fee: Optional[int] = Field(None, ge=0)
    
    # 決済状態の手動更新（店頭レジ会計用）
    payment_status: Optional[PaymentStatus] = None
    payment_method: Optional[PaymentMethod] = None

class ReceiptResponse(BaseModel):
    id: int
    tracking_token: str
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
    scheduled_start_at: Optional[datetime]
    estimated_duration: Optional[int]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    notification_sent_at: Optional[datetime]
    
    # 料金 & 決済レスポンス
    base_fee: int
    parts_fee: int
    additional_fee: int
    total_fee: int
    payment_status: str
    payment_method: Optional[str]
    payment_transaction_id: Optional[str]
    paid_at: Optional[datetime]

    class Config:
        from_attributes = True

class CheckoutRequest(BaseModel):
    payment_method: PaymentMethod = Field(PaymentMethod.amazon_pay, description="決済手段")

class PublicTrackResponse(BaseModel):
    tracking_token: str
    model: str
    color: str
    work_type: str
    status: str
    lane_id: str
    due_date: Optional[datetime]
    completed_at: Optional[datetime]
    base_fee: int
    parts_fee: int
    additional_fee: int
    total_fee: int
    payment_status: str

    class Config:
        from_attributes = True


# ── FastAPI App ──
app = FastAPI(title="Bicycle DX API", version="2.2.0")

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

def recalculate_total_fee(db_receipt: Receipt):
    """合計金額の自動計算ロジック"""
    db_receipt.total_fee = (db_receipt.base_fee or 0) + (db_receipt.parts_fee or 0) + (db_receipt.additional_fee or 0)

def send_completion_notification_stub(receipt_id: int, customer_name: str, contact: str, tracking_token: str):
    print(f"==================================================")
    print(f"【SMS通知スタブ実行】宛先: {customer_name} 様 ({contact})")
    print(f"URL: https://your-domain.com/track/{tracking_token}")
    print(f"==================================================")


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
            hour=payload.due_hour, minute=payload.due_minute, second=0, microsecond=0
        ).replace(tzinfo=None)

    calculated_start_date = None
    if payload.scheduled_start_days_offset is not None and payload.scheduled_start_hour is not None:
        target_start = datetime.now(JST) + timedelta(days=payload.scheduled_start_days_offset)
        calculated_start_date = target_start.replace(
            hour=payload.scheduled_start_hour, minute=payload.scheduled_start_minute or 0, second=0, microsecond=0
        ).replace(tzinfo=None)

    final_duration = payload.estimated_duration or DEFAULT_DURATION_MAP.get(payload.work_type)
    unique_token = secrets.token_urlsafe(16)

    db_receipt = Receipt(
        tracking_token=unique_token,
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
        lane_id=payload.lane_id.value,
        scheduled_start_at=calculated_start_date,
        estimated_duration=final_duration,
        base_fee=payload.base_fee,
        parts_fee=payload.parts_fee,
        additional_fee=payload.additional_fee,
    )
    
    recalculate_total_fee(db_receipt)

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
    job_category: Optional[JobCategory] = Query(None),
    status: Optional[ReceiptStatus] = Query(None),
    lane_id: Optional[LaneLocation] = Query(None),
    mechanic: Optional[StaffMember] = Query(None),
    keyword: Optional[str] = Query(None),
    sort_by: SortField = Query(SortField.due_date),
    sort_order: SortOrder = Query(SortOrder.asc),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    query = db.query(Receipt)
    if job_category: query = query.filter(Receipt.job_category == job_category.value)
    if status: query = query.filter(Receipt.status == status.value)
    if lane_id: query = query.filter(Receipt.lane_id == lane_id.value)
    if mechanic: query = query.filter(Receipt.mechanic == mechanic.value)
    if keyword:
        search_pattern = f"%{keyword}%"
        query = query.filter(
            or_(
                Receipt.customer_name.ilike(search_pattern),
                Receipt.contact.ilike(search_pattern),
                Receipt.maker.ilike(search_pattern),
                Receipt.model.ilike(search_pattern)
            )
        )
        
    sort_column = getattr(Receipt, sort_by.value)
    if sort_order == SortOrder.asc:
        query = query.order_by(nullslast(asc(sort_column)))
    else:
        query = query.order_by(nullsfirst(desc(sort_column)))

    return query.offset(offset).limit(limit).all()


@app.patch("/receipts/{receipt_id}", response_model=ReceiptResponse)
def update_receipt(
    receipt_id: int,
    payload: ReceiptUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    db_item = db.query(Receipt).filter(Receipt.id == receipt_id).first()
    if not db_item:
        raise HTTPException(status_code=404, detail="指定された受付伝票が見つかりません")
    
    if payload.customer_name is not None: db_item.customer_name = payload.customer_name
    if payload.contact is not None: db_item.contact = payload.contact
    if payload.job_category is not None: db_item.job_category = payload.job_category.value
    if payload.receptionist is not None: db_item.receptionist = payload.receptionist.value
    if payload.mechanic is not None: db_item.mechanic = payload.mechanic.value
    if payload.lane_id is not None: db_item.lane_id = payload.lane_id.value
    if payload.maker is not None: db_item.maker = payload.maker.value
    if payload.maker_other is not None: db_item.maker_other = payload.maker_other
    if payload.model is not None: db_item.model = payload.model
    if payload.color is not None: db_item.color = payload.color.value
    
    if payload.work_type is not None:
        db_item.work_type = payload.work_type.value
        if payload.estimated_duration is None:
            db_item.estimated_duration = DEFAULT_DURATION_MAP.get(payload.work_type)
    if payload.work_type_other is not None: db_item.work_type_other = payload.work_type_other
        
    # ステータス更新 & 自動タイムスタンプ & 完了通知キック
    if payload.status is not None:
        db_item.status = payload.status.value
        if payload.status == ReceiptStatus.repairing and db_item.started_at is None:
            db_item.started_at = datetime.now(JST).replace(tzinfo=None)
        elif payload.status in [ReceiptStatus.waiting_payment, ReceiptStatus.completed]:
            if db_item.completed_at is None:
                db_item.completed_at = datetime.now(JST).replace(tzinfo=None)
            
            if db_item.notification_sent_at is None:
                background_tasks.add_task(
                    send_completion_notification_stub,
                    db_item.id, db_item.customer_name, db_item.contact, db_item.tracking_token
                )
                db_item.notification_sent_at = datetime.now(JST).replace(tzinfo=None)

    # 料金更新 ＆ 合計自動再計算（遺品②）
    if payload.base_fee is not None: db_item.base_fee = payload.base_fee
    if payload.parts_fee is not None: db_item.parts_fee = payload.parts_fee
    if payload.additional_fee is not None: db_item.additional_fee = payload.additional_fee
    recalculate_total_fee(db_item)

    # 店頭での手動決済更新
    if payload.payment_status is not None: db_item.payment_status = payload.payment_status.value
    if payload.payment_method is not None: db_item.payment_method = payload.payment_method.value

    if payload.estimated_duration is not None: db_item.estimated_duration = payload.estimated_duration
    if payload.started_at is not None: db_item.started_at = payload.started_at
    if payload.completed_at is not None: db_item.completed_at = payload.completed_at

    # 着手予定更新
    if payload.clear_scheduled_start is True:
        db_item.scheduled_start_at = None
    elif payload.scheduled_start_days_offset is not None or payload.scheduled_start_hour is not None:
        base_start = db_item.scheduled_start_at or datetime.now(JST).replace(tzinfo=None)
        if payload.scheduled_start_days_offset is not None:
            base_start = (datetime.now(JST) + timedelta(days=payload.scheduled_start_days_offset)).replace(tzinfo=None)
        start_hour = payload.scheduled_start_hour if payload.scheduled_start_hour is not None else base_start.hour
        start_minute = payload.scheduled_start_minute if payload.scheduled_start_minute is not None else base_start.minute
        db_item.scheduled_start_at = base_start.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
        
    # 納期更新
    has_due_update = (payload.is_pending_contact is True or payload.due_days_offset is not None or payload.due_hour is not None or payload.due_minute is not None)
    if has_due_update:
        if payload.is_pending_contact is True:
            db_item.due_date = None
        else:
            base_due = db_item.due_date or datetime.now(JST).replace(tzinfo=None)
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


# ── お客様用（公開）進捗照会＆モック決済 API（遺品③・④） ──

@app.get("/public/track/{tracking_token}", response_model=PublicTrackResponse)
def get_public_track(tracking_token: str, db: Session = Depends(get_db)):
    db_item = db.query(Receipt).filter(Receipt.tracking_token == tracking_token).first()
    if not db_item:
        raise HTTPException(status_code=404, detail="指定された進捗情報が見つかりません")
    return db_item


@app.post("/public/track/{tracking_token}/checkout", response_model=PublicTrackResponse)
def mock_checkout(
    tracking_token: str,
    payload: CheckoutRequest,
    db: Session = Depends(get_db)
):
    """Amazon Pay/Web決済モックAPI」"""
    receipt = db.query(Receipt).filter(Receipt.tracking_token == tracking_token).first()
    if not receipt:
        raise HTTPException(status_code=404, detail="伝票が見つかりません")

    if receipt.payment_status == PaymentStatus.paid.value:
        raise HTTPException(status_code=400, detail="既に決済が完了しています")

    now_jst = datetime.now(JST).replace(tzinfo=None)
    mock_charge_id = f"P01-AMZN-{secrets.token_hex(6).upper()}"

    receipt.payment_status = PaymentStatus.paid.value
    receipt.payment_method = payload.payment_method.value
    receipt.payment_transaction_id = mock_charge_id
    receipt.paid_at = now_jst

    # 決済完了したら「決済待ち」から「引き渡し待機」レーンへ昇格
    if receipt.status == ReceiptStatus.waiting_payment.value:
        receipt.lane_id = LaneLocation.waiting_delivery.value

    print(f"💰【Amazon Pay決済モック成功】{receipt.customer_name} 様 合計: ¥{receipt.total_fee:,} (取引ID: {mock_charge_id})")

    try:
        db.commit()
        db.refresh(receipt)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"決済処理エラー: {str(e)}")

    return receipt