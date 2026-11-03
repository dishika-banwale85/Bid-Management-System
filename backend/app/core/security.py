from datetime import datetime, timedelta, timezone
import jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.core.config import JWT_SECRET, JWT_EXPIRE_MINUTES
from app.db import get_db
from app.models import User

ALGORITHM = "HS256"
oauth2 = OAuth2PasswordBearer(tokenUrl="/auth/login")
passwords=CryptContext(schemes=["bcrypt"],deprecated="auto")

def hash_password(password: str) -> str:
    return passwords.hash(password)

def verify_password(password: str, hashed: str) -> bool:
    try: return passwords.verify(password,hashed)
    except (ValueError, TypeError): return False

def create_token(user: User) -> str:
    return jwt.encode({"sub": str(user.id), "exp": datetime.now(timezone.utc)+timedelta(minutes=JWT_EXPIRE_MINUTES)}, JWT_SECRET, algorithm=ALGORITHM)

def current_user(token: str = Depends(oauth2), db: Session = Depends(get_db)) -> User:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        user = db.get(User, int(payload["sub"]))
    except (jwt.PyJWTError, ValueError, KeyError):
        raise HTTPException(status_code=401, detail={"error":"unauthorized","message":"Invalid or expired token"})
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail={"error":"unauthorized","message":"User is unavailable"})
    return user

def require_role(*roles: str):
    def dependency(user: User = Depends(current_user)):
        if user.role.name not in roles:
            raise HTTPException(status_code=403, detail={"error":"forbidden","message":"Role is not permitted for this action"})
        return user
    return dependency

def deny_admin_writes(user: User = Depends(current_user)) -> User:
    if user.role.name=="ADMIN":
        raise HTTPException(status_code=403,detail={"error":"forbidden","message":"Administrators have read-only access to compliance requests"})
    return user
