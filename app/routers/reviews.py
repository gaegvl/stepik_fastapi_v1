from fastapi import APIRouter, HTTPException, Depends, status, Path, Body
from typing import Annotated
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select, update
from app.auth import UserModel, get_current_buyer, get_current_user
from app.db_depends import get_db
from app.routers.products import ProductModel
from app.models.reviews import Review as ReviewsModel
from app.schemas import ReviewCreate, Review as ReviewSchema

router = APIRouter(prefix="/reviews", tags=["reviews"])


async def calc_avg_grade(
    product_id: int, db: Annotated[AsyncSession, Depends(get_db)]
) -> float:
    avg_grade = (
        await db.scalar(
            select(func.avg(ReviewsModel.grade)).where(
                ReviewsModel.product_id == product_id, ReviewsModel.is_active
            )
        )
        or 0.0
    )
    return avg_grade


@router.get("/", response_model=list[ReviewSchema], status_code=status.HTTP_200_OK)
async def get_all_reviews(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[ReviewSchema]:
    result = await db.scalars(select(ReviewsModel).where(ReviewsModel.is_active))
    return result.all()


@router.post("/", response_model=ReviewSchema, status_code=status.HTTP_201_CREATED)
async def create_review(
    review: Annotated[ReviewCreate, Body()],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(get_current_buyer)],
) -> ReviewSchema:
    product = await db.scalar(
        select(ProductModel).where(
            ProductModel.id == review.product_id, ProductModel.is_active
        )
    )
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found or inactive",
        )

    new_review = ReviewsModel(**review.model_dump(), user_id=current_user.id)
    db.add(new_review)
    await db.flush()
    avg_grade = await calc_avg_grade(review.product_id, db)
    if avg_grade > 5 or avg_grade < 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Average grade must be between 1 and 5",
        )
    product.rating = avg_grade
    await db.commit()
    return new_review


@router.delete("/{review_id}", status_code=status.HTTP_200_OK)
async def delete_review(
    review_id: Annotated[int, Path()],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(get_current_user)],
) -> dict[str, str]:
    review = await db.scalar(
        select(ReviewsModel).where(ReviewsModel.id == review_id, ReviewsModel.is_active)
    )
    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Review not found or inactive"
        )

    if current_user.role != "admin" and current_user.id != review.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins or the reviewer can delete this review",
        )

    review.is_active = False
    avg_grade = await calc_avg_grade(review.product_id, db)
    if avg_grade > 5 or avg_grade < 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Average grade must be between 1 and 5",
        )
    await db.execute(
        update(ProductModel)
        .where(ProductModel.id == review.product_id)
        .values(rating=avg_grade)
    )
    await db.commit()
    return {"status": "success", "message": "Review deleted successfully"}
