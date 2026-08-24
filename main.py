from fastapi import FastAPI, Depends, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, DateTime, or_, asc, desc, nullslast, nullsfirst
from sqlalchemy.orm import sessionmaker, Session, declarative_base
import os
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from enum import Enum
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

# ── 作業種別ごとの標準目安所要時間（分） ──
# ※ オーバーホールやその他は現物確認・分解後の見積もりとなるため None（未定）
DEFAULT_DURATION_MAP = {
    WorkType.puncture: 15,                  # パンク修理: 15分
    WorkType.brake_adjustment: 20,          # ブレーキ調整・交換: 20分
    WorkType.derailleur_adjustment: 15,      # 変速調整: 15分
    WorkType.cable_external: 20,            # ワイヤー交換（外通し）: 20分
    WorkType.cable_internal: 45,            # ワイヤー交換（フレーム内装）: 45分（※LOOK 795等は手動延長推奨）
    WorkType.tire_replacement: 30,          # タイヤ・チューブ交換: 30分
    WorkType.new_assembly: 60,              # 新車組み立て: 60分
    WorkType.general_inspection: None,      # 定期点検・オーバーホール: 現物見積のため未定
    WorkType.other: None,                   # その他: 現物見積のため未定
}

# ── ソート用 Enum ──
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
    customer_name = Column(String, index=True, nullable=False)
    contact = Column(String, index=True, nullable=False)              # 電話番号検索用
    job_category = Column(String, index=True, nullable=False)
    receptionist = Column(String, nullable=False)
    mechanic = Column(String, index=True, nullable=True)             # 担当メカニック絞り込み用
    maker = Column(String, index=True, nullable=False)                # メーカー検索・集計用
    maker_other = Column(String, nullable=True)
    model = Column(String, index=True, nullable=False)                # 車種検索用
    color = Column(String, nullable=False)
    work_type = Column(String, nullable=False)
    work_type_other = Column(String, nullable=True)
    status = Column(String, index=True, nullable=False)              # ステータス絞り込み用
    created_at = Column(DateTime, index=True, nullable=False)        # 受付日時ソート・期間絞り込み用
    due_date = Column(DateTime, index=True, nullable=True)           # 納期ソート・アラート用（デフォルトソート）
    lane_id = Column(String, index=True, nullable=False)             # レーン絞り込み用
    
    # ── スケジュール・工数管理 ──
    scheduled_start_at = Column(DateTime, index=True, nullable=True) # 着手予定ソート用
    estimated_duration = Column(Integer, nullable=True)              # 目安所要時間（分単位）
    started_at = Column(DateTime, nullable=True)                     # 実作業開始日時
    completed_at = Column(DateTime, nullable=True)                   # 実作業完了日時

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
    
    # 約束納期
    due_days_offset: Optional[int] = Field(0, description="納期の日数オフセット（0=当日, 1=明日... None=要確認）")
    due_hour: int = Field(15, ge=0, le=23, description="納期の時間（時）")
    due_minute: int = Field(0, ge=0, le=59, description="納期の時間（分）")
    
    # スケジュール・工数の指定（任意）
    scheduled_start_days_offset: Optional[int] = Field(None, description="着手予定日の日数オフセット（0=当日, 1=明日...）")
    scheduled_start_hour: Optional[int] = Field(None, ge=0, le=23, description="着手予定時間（時）")
    scheduled_start_minute: Optional[int] = Field(0, ge=0, le=59, description="着手予定時間（分）")
    estimated_duration: Optional[int] = Field(None, ge=1, description="目安所要時間（分単位：例 30）")

class ReceiptUpdate(BaseModel):
    # 顧客情報
    customer_name: Optional[str] = Field(None, description="顧客名の変更")
    contact: Optional[str] = Field(None, description="連絡先の変更")
    
    # 案件・担当者・ステータス
    job_category: Optional[JobCategory] = None
    receptionist: Optional[StaffMember] = None
    mechanic: Optional[StaffMember] = None
    status: Optional[ReceiptStatus] = None
    lane_id: Optional[LaneLocation] = None
    
    # 車両情報
    maker: Optional[BicycleMaker] = None
    maker_other: Optional[str] = Field(None, description="メーカー『その他』の詳細")
    model: Optional[str] = Field(None, description="車種名")
    color: Optional[BicycleColor] = None
    
    # 作業種別
    work_type: Optional[WorkType] = None
    work_type_other: Optional[str] = Field(None, description="作業『その他』の詳細")
    
    # 納期関連
    due_days_offset: Optional[int] = Field(None, description="納期の日数を変更")
    due_hour: Optional[int] = Field(None, ge=0, le=23, description="納期の時間を変更")
    due_minute: Optional[int] = Field(None, ge=0, le=59, description="納期の分を変更")
    is_pending_contact: Optional[bool] = Field(None, description="Trueにすると納期を『要確認（Null）』に変更")
    
    # 着手予定・工数関連
    scheduled_start_days_offset: Optional[int] = Field(None, description="着手予定日の日数を変更")
    scheduled_start_hour: Optional[int] = Field(None, ge=0, le=23, description="着手予定時間を変更（時）")
    scheduled_start_minute: Optional[int] = Field(None, ge=0, le=59, description="着手予定時間を変更（分）")
    clear_scheduled_start: Optional[bool] = Field(None, description="Trueにすると着手予定日時をクリア（Null）")
    estimated_duration: Optional[int] = Field(None, ge=1, description="目安所要時間（分）を変更")
    started_at: Optional[datetime] = Field(None, description="実作業開始日時の手動更新")
    completed_at: Optional[datetime] = Field(None, description="実作業完了日時の手動更新")

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
    
    # スケジュール・工数
    scheduled_start_at: Optional[datetime]
    estimated_duration: Optional[int]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]

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
    
    # 納期の動的計算
    calculated_due_date = None
    if payload.due_days_offset is not None:
        target_date = datetime.now(JST) + timedelta(days=payload.due_days_offset)
        calculated_due_date = target_date.replace(
            hour=payload.due_hour,
            minute=payload.due_minute,
            second=0,
            microsecond=0
        ).replace(tzinfo=None)

    # 着手予定日時の動的計算
    calculated_start_date = None
    if payload.scheduled_start_days_offset is not None and payload.scheduled_start_hour is not None:
        target_start = datetime.now(JST) + timedelta(days=payload.scheduled_start_days_offset)
        calculated_start_date = target_start.replace(
            hour=payload.scheduled_start_hour,
            minute=payload.scheduled_start_minute or 0,
            second=0,
            microsecond=0
        ).replace(tzinfo=None)

    # 作業時間の自動補完（未指定時は作業種別の標準目安時間を適用）
    final_duration = payload.estimated_duration
    if final_duration is None:
        final_duration = DEFAULT_DURATION_MAP.get(payload.work_type)

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
        lane_id=payload.lane_id.value,
        scheduled_start_at=calculated_start_date,
        estimated_duration=final_duration,
        started_at=None,
        completed_at=None
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
    sort_by: SortField = Query(SortField.due_date, description="ソート基準カラム（デフォルト: 約束納期順）"),
    sort_order: SortOrder = Query(SortOrder.asc, description="ソート順（昇順 asc / 降順 desc）"),
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
                Receipt.contact.ilike(search_pattern),
                Receipt.maker.ilike(search_pattern),
                Receipt.maker_other.ilike(search_pattern),
                Receipt.model.ilike(search_pattern),
                Receipt.work_type_other.ilike(search_pattern)
            )
        )
        
    # ── ソート処理（未設定・NULL値は昇順時は末尾、降順時は先頭に配置） ──
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
    db: Session = Depends(get_db)
):
    db_item = db.query(Receipt).filter(Receipt.id == receipt_id).first()
    if not db_item:
        raise HTTPException(status_code=404, detail="指定された受付伝票が見つかりません")
    
    # ── 顧客情報の更新 ──
    if payload.customer_name is not None:
        db_item.customer_name = payload.customer_name
    if payload.contact is not None:
        db_item.contact = payload.contact
        
    # ── 案件・担当者・レーンの更新 ──
    if payload.job_category is not None:
        db_item.job_category = payload.job_category.value
    if payload.receptionist is not None:
        db_item.receptionist = payload.receptionist.value
    if payload.mechanic is not None:
        db_item.mechanic = payload.mechanic.value
    if payload.lane_id is not None:
        db_item.lane_id = payload.lane_id.value
        
    # ── 車両情報の更新 ──
    if payload.maker is not None:
        db_item.maker = payload.maker.value
    if payload.maker_other is not None:
        db_item.maker_other = payload.maker_other
    if payload.model is not None:
        db_item.model = payload.model
    if payload.color is not None:
        db_item.color = payload.color.value
        
    # ── 作業種別の更新 ──
    if payload.work_type is not None:
        db_item.work_type = payload.work_type.value
        # 作業種別が変更され、所要時間が明示されていない場合は標準目安時間を適用
        if payload.estimated_duration is None:
            db_item.estimated_duration = DEFAULT_DURATION_MAP.get(payload.work_type)
    if payload.work_type_other is not None:
        db_item.work_type_other = payload.work_type_other
        
    # ── ステータス更新 & 自動タイムスタンプ ──
    if payload.status is not None:
        db_item.status = payload.status.value
        # 「整備中」になったら作業開始日時を自動記録（未記録の場合）
        if payload.status == ReceiptStatus.repairing and db_item.started_at is None:
            db_item.started_at = datetime.now(JST).replace(tzinfo=None)
        # 「決済待ち」または「引渡完了」になったら完了日時を自動記録（未記録の場合）
        elif payload.status in [ReceiptStatus.waiting_payment, ReceiptStatus.completed] and db_item.completed_at is None:
            db_item.completed_at = datetime.now(JST).replace(tzinfo=None)

    # ── 工数・日時の手動更新（指定がある場合） ──
    if payload.estimated_duration is not None:
        db_item.estimated_duration = payload.estimated_duration
    if payload.started_at is not None:
        db_item.started_at = payload.started_at
    if payload.completed_at is not None:
        db_item.completed_at = payload.completed_at

    # ── 着手予定日時の更新 ──
    if payload.clear_scheduled_start is True:
        db_item.scheduled_start_at = None
    elif (
        payload.scheduled_start_days_offset is not None
        or payload.scheduled_start_hour is not None
        or payload.scheduled_start_minute is not None
    ):
        base_start = db_item.scheduled_start_at if db_item.scheduled_start_at else datetime.now(JST).replace(tzinfo=None)
        if payload.scheduled_start_days_offset is not None:
            base_start = (datetime.now(JST) + timedelta(days=payload.scheduled_start_days_offset)).replace(tzinfo=None)
            
        start_hour = payload.scheduled_start_hour if payload.scheduled_start_hour is not None else base_start.hour
        start_minute = payload.scheduled_start_minute if payload.scheduled_start_minute is not None else base_start.minute
        db_item.scheduled_start_at = base_start.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
        
    # ── 納期関連のパラメータ指定がある場合のみ更新 ──
    has_due_update = (
        payload.is_pending_contact is True
        or payload.due_days_offset is not None
        or payload.due_hour is not None
        or payload.due_minute is not None
    )

    if has_due_update:
        if payload.is_pending_contact is True:
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