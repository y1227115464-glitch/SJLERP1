import argparse
import getpass
import os
import sys

from pydantic import ValidationError
from sqlalchemy import select

from app.core.api import audit
from app.core.config import Settings
from app.core.database import Database
from app.core.security import hash_password
from app.models import User
from app.schemas import UserCreate


def main():
    parser = argparse.ArgumentParser(description="书剑录 ERP 管理工具")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-admin", help="创建管理员，不生成默认账号或密码")
    create.add_argument("--email")
    create.add_argument("--name", default="系统管理员")
    commands.add_parser("recover-jobs", help="恢复未入队任务，标记中断任务")
    args = parser.parse_args()
    if args.command == "recover-jobs":
        from app.jobs.service import recover_jobs
        print(recover_jobs())
        return
    email = args.email or input("管理员邮箱：").strip()
    password = os.environ.get("SJL_BOOTSTRAP_PASSWORD")
    if not password:
        if not sys.stdin.isatty():
            parser.error("非交互环境请通过 SJL_BOOTSTRAP_PASSWORD 提供密码")
        password = getpass.getpass("密码（至少 12 个字符）：")
        if password != getpass.getpass("再次输入密码："):
            parser.error("两次密码输入不一致")
    try:
        payload = UserCreate(email=email, display_name=args.name, password=password, role="admin")
    except ValidationError:
        parser.error("邮箱、姓名或密码格式无效；密码至少 12 个字符")
    database = Database(Settings())
    with database.session() as db:
        if db.scalar(select(User).where(User.email == payload.email)):
            parser.error("该邮箱账号已存在，未修改现有账号")
        user = User(email=payload.email, display_name=payload.display_name, password_hash=hash_password(payload.password), role="admin")
        db.add(user)
        db.flush()
        audit(db, None, "users.bootstrap", "user", user.id, "通过管理工具初始化管理员")
        db.commit()
    print(f"管理员已创建：{payload.email}")


if __name__ == "__main__":
    main()
