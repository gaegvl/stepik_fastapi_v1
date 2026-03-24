from fastapi import APIRouter, Body, Depends, HTTPException, status
from app.config import ALGORITHM, SECRET_KEY
from app.db_depends import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi.security import OAuth2PasswordRequestForm
import jwt


from typing import Annotated
from app.models.users import User as UserModel
from app.schemas import RefreshTokenRequest, UserCreate, User as UserSchema
from app.auth import hash_password, verify_password, create_access_token, create_refresh_token


router = APIRouter(prefix="/users", tags=["users"])


credential_exception = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate refresh token", headers={"WWW-Authenticate":"Bearer"})

@router.post("/", response_model=UserSchema, status_code=status.HTTP_201_CREATED)
async def create_user(user:Annotated[UserCreate, Body], db:Annotated[AsyncSession, Depends(get_db)]) -> UserSchema:
    result = await db.scalar(select(UserModel).where(UserModel.email == user.email))
    if result:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    db_user = UserModel(email=user.email, hashed_password=hash_password(user.password), role=user.role)
    db.add(db_user)
    await db.commit()
    return db_user

@router.post('/token')
async def login(form_data:Annotated[OAuth2PasswordRequestForm, Depends()], db:Annotated[AsyncSession, Depends(get_db)]) -> dict[str, str]:
    user = await db.scalar(select(UserModel).where(UserModel.email == form_data.username, UserModel.is_active))
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password", headers={"WWW-Authenticate":"Bearer"})
    access_token = create_access_token(data={"sub":user.email, "role": user.role, "id": user.id})
    refresh_token = create_refresh_token(data={"sub":user.email, "role": user.role, "id": user.id})
    return {"access_token": access_token, "refresh_token": refresh_token, "token_type": "bearer"}
        
@router.post('/refresh-token')
async def refresh_token(refresh_token:Annotated[RefreshTokenRequest, Body()], db:Annotated[AsyncSession, Depends(get_db)]) -> dict[str, str]:
    old_refresh_token = refresh_token.refresh_token
    try:
        payload = jwt.decode(old_refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str|None = payload.get("sub")
        token_type: str|None = payload.get("token_type")

        if email is None or token_type != "refresh":
            raise credential_exception
    except jwt.ExpiredSignatureError:
        raise credential_exception
    except jwt.PyJWTError:
        raise credential_exception
    user = await db.scalar(select(UserModel).where(UserModel.email == email, UserModel.is_active))
    if not user:
        raise credential_exception
    
    new_refresh_token = create_refresh_token(data={"sub":user.email, "role": user.role, "id": user.id})
    return {"refresh_token": new_refresh_token, "token_type":"bearer"}

@router.post('/access-token')
async def get_access_token(refresh_token:Annotated[RefreshTokenRequest, Body()], db:Annotated[AsyncSession, Depends(get_db)]) -> dict[str, str]:
    try:
        payload = jwt.decode(refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str|None = payload.get("sub")
        token_type:str|None = payload.get("token_type")

        if not email or token_type != "refresh":
            raise credential_exception
    except jwt.jwt.ExpiredSignatureError:
        raise credential_exception
    except jwt.PyJWTError:
        raise credential_exception
    
    user = await db.scalar(select(UserModel).where(UserModel.email == email, UserModel.is_active))
    if not user:
        raise credential_exception

    new_access_token = create_access_token(data={"sub":user.email, "role": user.role, "id": user.id})
    return {"access_token": new_access_token, "token_type": "bearer"}