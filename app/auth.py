from typing import Annotated
from passlib.context import CryptContext
from fastapi.security import OAuth2PasswordBearer
from datetime import datetime, timedelta, timezone
import jwt

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select 

from app.models.users import User as UserModel
from app.config import SECRET_KEY, ALGORITHM
from app.db_depends import get_db

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


ACCESS_TOKE_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 7

oauth2_scheme = OAuth2PasswordBearer(tokenUrl='users/token')

def hash_password(password:str) -> str:
    return pwd_context.hash(password)

def verify_password(plaint_password:str, hashed_password: str) -> bool:
    return pwd_context.verify(plaint_password, hashed_password)

def create_access_token(data:dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKE_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "token_type": "access"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def create_refresh_token(data:dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp":expire, "token_type":"refresh"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token:Annotated[str, Depends(oauth2_scheme)], db:Annotated[AsyncSession, Depends(get_db)]) -> UserModel:
    credential_exception = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials", headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email:str|None = payload.get("sub")
        token_type:str|None = payload.get("token_type")
        if email is None or token_type != "access":
            raise credential_exception
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired", headers={"WWW-Authenticate": "Bearer"})
    except jwt.PyJWTError:
        raise credential_exception
    user = await db.scalar(select(UserModel).where(UserModel.email == email, UserModel.is_active))
    if user is None:
        raise credential_exception
    return user

def get_current_buyer(current_user:Annotated[UserModel, Depends(get_current_user)]) -> UserModel:
    if current_user.role != "buyer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only buyers can perform this action")
    return current_user

def get_current_seller(current_user:Annotated[UserModel, Depends(get_current_user)]) -> UserModel:
    if current_user.role != "seller":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only sellers can perform this action")
    return current_user

def get_current_admin(current_user:Annotated[UserModel, Depends(get_current_user)]) -> UserModel:
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can perform this action")
    return current_user