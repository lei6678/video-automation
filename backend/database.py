"""
数据库配置 - SQLite
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from _resource import get_data_dir

# 数据库文件路径: data/app.db（开发在 backend/data/，打包后在 exe 同目录 data/）
DATABASE_DIR = get_data_dir()
DATABASE_PATH = os.path.join(DATABASE_DIR, "app.db")

# 创建数据库引擎
engine = create_engine(f"sqlite:///{DATABASE_PATH}", connect_args={"check_same_thread": False})

# 创建会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 基础模型类
Base = declarative_base()


def get_db():
    """获取数据库会话的依赖"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()