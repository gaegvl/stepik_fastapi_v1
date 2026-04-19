from typing import Annotated
from fastapi import APIRouter, status, Depends, HTTPException, Body, Path
from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.categories import Category as CategoryModel
from app.schemas import CategoryCreate, Category as CategorySchema
from app.db_depends import get_db


router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("/", response_model=list[CategorySchema], status_code=status.HTTP_200_OK)
async def get_all_categories(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[CategorySchema]:
    stmt = select(CategoryModel).where(CategoryModel.is_active)
    categories = await db.scalars(stmt)
    return categories.all()


@router.post("/", response_model=CategorySchema, status_code=status.HTTP_201_CREATED)
async def create_category(
    category: Annotated[CategoryCreate, Body()],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CategorySchema:
    if category.parent_id is not None:
        stmt = select(CategoryModel).where(
            CategoryModel.id == category.parent_id, CategoryModel.is_active
        )

        result = await db.scalars(stmt)
        parent = result.first()
        if not parent:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Parent category not found",
            )

    db_category = CategoryModel(**category.model_dump())
    db.add(db_category)
    await db.commit()
    return db_category


@router.put(
    "/{category_id}", response_model=CategorySchema, status_code=status.HTTP_200_OK
)
async def update_category(
    category_id: Annotated[int, Path()],
    category: Annotated[CategoryCreate, Body()],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CategorySchema:
    result = await db.scalars(
        select(CategoryModel).where(CategoryModel.id == category_id)
    )
    ctg: CategoryModel | None = result.first()
    if not ctg:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Category not found"
        )

    if category.parent_id is not None:
        result = await db.scalars(
            select(CategoryModel).where(
                and_(CategoryModel.id == category.parent_id, CategoryModel.is_active)
            )
        )
        parent: CategoryModel | None = result.first()
        if not parent:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Parent category not found",
            )

    await db.execute(
        update(CategoryModel)
        .where(CategoryModel.id == category_id)
        .values(is_active=True, **category.model_dump())
    )
    await db.commit()
    await db.refresh(ctg)
    return ctg


@router.delete("/{category_id}", status_code=status.HTTP_200_OK)
async def delete_category(
    category_id: Annotated[int, Path()], db: Annotated[AsyncSession, Depends(get_db)]
) -> dict:
    result = await db.scalars(
        select(CategoryModel).where(
            and_(CategoryModel.is_active, CategoryModel.id == category_id)
        )
    )
    category: CategoryModel | None = result.first()
    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Category not found!"
        )

    await db.execute(
        update(CategoryModel)
        .where(CategoryModel.id == category.id)
        .values(is_active=False)
    )
    await db.commit()
    return {"status": "Success", "message": "Category make is inactive!"}
