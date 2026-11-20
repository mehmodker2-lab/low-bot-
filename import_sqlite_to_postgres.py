# -*- coding: utf-8 -*-
"""
نقل بيانات البوت من SQLite (channels.db) إلى قاعدة Supabase/PostgreSQL.
آمن ويعمل أكثر من مرة (لا يكرر الصفوف، ولا يمسح شيئاً موجوداً).

الاستخدام:
    set DATABASE_URL=postgresql://...pooler...:6543/postgres
    python import_sqlite_to_postgres.py

خيارات:
    python import_sqlite_to_postgres.py --db مسار/channels.db
"""
import os
import sys
import sqlite3
import argparse

try:
    import psycopg2
except ImportError:
    print("❌ مكتبة psycopg2 غير منصبة. نفّذ: pip install psycopg2-binary")
    sys.exit(1)

# ترتيب مهم: الأب قبل الابن (لا يوجد FK هنا لكن للترتيب المنطقي)
TABLES = [
    "channels",
    "admins",
    "bot_users",
    "listing_requests",
    "bot_settings",
    "blacklist",
    "sent_messages",
    "pending_messages",
    "scheduled_deletions",
    "channel_strikes",
    "deletion_suppressions",
]
SERIAL_TABLES = [t for t in TABLES if t != "bot_settings"]


def normalize(url: str) -> str:
    url = (url or "").strip().strip('"').strip("'")
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if "supabase" in url and "sslmode=" not in url:
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return url


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "channels.db"))
    args = ap.parse_args()

    url = normalize(os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL") or "")
    if not url:
        print("❌ ضع DATABASE_URL (رابط Supabase Pooler منفذ 6543) قبل التشغيل.")
        return 1
    if not os.path.exists(args.db):
        print(f"❌ لم أجد ملف SQLite: {args.db}")
        return 1

    print(f"📂 المصدر : {args.db}")
    print(f"🐘 الهدف  : {url.split('@')[-1]}")
    src = sqlite3.connect(args.db)
    src.row_factory = sqlite3.Row
    try:
        dst = psycopg2.connect(url, connect_timeout=15)
    except Exception as e:
        print(f"❌ تعذّر الاتصال بقاعدة PostgreSQL: {e}")
        print("💡 تأكد أن الرابط هو Pooler (منفذ 6543) وأن كلمة المرور صحيحة.")
        return 1
    dst.autocommit = False
    cur = dst.cursor()

    total = 0
    for table in TABLES:
        try:
            rows = src.execute(f"SELECT * FROM {table}").fetchall()
        except sqlite3.Error:
            print(f"⏭️  {table}: غير موجود في SQLite — تم التخطي")
            continue
        if not rows:
            print(f"•  {table}: 0 صف")
            continue

        cur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s", (table,)
        )
        pg_cols = {r[0] for r in cur.fetchall()}
        if not pg_cols:
            print(f"⏭️  {table}: غير موجود في PostgreSQL — تم التخطي")
            continue

        cols = [c for c in rows[0].keys() if c in pg_cols]
        if not cols:
            print(f"⏭️  {table}: لا أعمدة مشتركة — تم التخطي")
            continue

        placeholders = ", ".join(["%s"] * len(cols))
        col_list = ", ".join(cols)
        sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"
        inserted = 0
        for row in rows:
            try:
                cur.execute(sql, tuple(row[c] for c in cols))
                inserted += cur.rowcount
            except Exception as e:
                print(f"   ⚠️ صف متعذر في {table}: {e}")
                dst.rollback()
                cur = dst.cursor()
                continue
        dst.commit()
        total += inserted
        print(f"✅ {table}: نُقل {inserted} من {len(rows)} صف")

    # إصلاح عدادات id التسلسلية بعد الإدخال بأرقام صريحة
    for table in SERIAL_TABLES:
        try:
            cur.execute(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {table}), 1))"
            )
        except Exception:
            dst.rollback()
            continue
    dst.commit()

    cur.close()
    src.close()
    dst.close()
    print(f"\n🎉 تم النقل بنجاح — إجمالي الصفوف المنقولة: {total}")
    print("افتح /healthz على Render للتأكد: db_engine = postgresql")
    return 0


if __name__ == "__main__":
    sys.exit(main())
