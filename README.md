# bicycle_dx_mvp

店舗業務（自転車修理受付・進捗管理・決済）の課題解決・DX化を想定して構築した、FastAPIおよびDocker/PostgreSQLによるWeb APIのMVP（最小限のプロダクト）プロトタイプです。

## 概要・目的
自転車整備現場における受付業務、作業レーン管理（ピット/倉庫）、工数・納期算出、およびお客様向けオンライン進捗確認・モック決済（Amazon Pay等）を一貫して管理するバックエンドAPIです。

## 主な機能・特徴
- **高度なドメインモデル設計:** 修理種別ごとの標準作業時間（工数）の自動割り当て、ステータス変更に伴う時間計測・自動タイムスタンプ更新。
- **タイムゾーン安全設計:** システム内部およびDBデータはすべてUTC（タイムゾーン情報付き）で保持し、日時指定入力および表示ロジックのみJST（UTC+9）で変換・計算。
- **非同期バックグラウンド処理:** 修理完了ステータス遷移時、`BackgroundTasks` を活用した顧客向けSMS完了通知（スタブ）の非同期実行。
- **公開用進捗照会 & オンライン決済モック:** トークンベースのお客様専用進捗確認APIおよび、決済完了時の自動レーン昇格ロジック。
- **堅牢なコンテナオーケストレーション:** `docker-compose` におけるPostgreSQLのヘルスチェック（`pg_isready`）および `service_healthy` 制御による起動順序の依存関係制御。

## 技術スタック
- **Language:** Python 3.10+
- **Framework:** FastAPI, Pydantic (v2)
- **ORM / Database:** SQLAlchemy, PostgreSQL 15 (Alpine)
- **Container / Environment:** Docker, Docker Compose
- **Server:** Uvicorn

## 起動手順（ローカル開発環境）

1. リポジトリのクローン
```bash
git clone [https://github.com/ciel93/bicycle_dx_mvp.git](https://github.com/ciel93/bicycle_dx_mvp.git)
cd bicycle_dx_mvp
2. 環境変数の設定
.env.example をコピーして .env を作成します（PostgreSQLの認証情報等を設定）。
cp .env.example .env
3. Docker Composeによるコンテナ起動
DBのヘルスチェック完了後、APIサーバーが自動起動します。
docker-compose up -d --build
4. 動作確認・APIドキュメント閲覧
コンテナ起動後、ブラウザで以下にアクセスすることで Swagger UI によるインタラクティブなAPI仕様書の閲覧・

## 今後の開発ロードマップ
- [ ] **フロントエンド開発（React / TypeScript）**
  - **店舗スタッフ用ダッシュボード:** レーン別の伝票カンバンボード表示、ステータス変更・工数入力UIの実装。
  - **顧客用進捗照会ポータル:** リアルタイム進捗ステータス表示およびWeb決済（Amazon Pay等）フローのUI実装。
- [ ] **認証・認可機能（JWT / OAuth2）:** 店舗スタッフ用ログイン・権限管理の実装。
