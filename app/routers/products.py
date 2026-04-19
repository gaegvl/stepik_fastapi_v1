from operator import eq, ge, le
from fastapi import APIRouter, Depends, Body, Path, status, HTTPException, Query
from sqlalchemy import desc, select, update, and_
from typing import Annotated, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, with_loader_criteria
from sqlalchemy.sql import func

from app.auth import get_current_seller
from app.models import Product as ProductModel, Category
from app.models.users import User as UserModel
from app.models.reviews import Review as ReviewsModel
from app.schemas import (
    ProductCreate,
    Product as ProductSchema,
    ProductFilter,
    ProductList,
    Review as ReviewSchema,
)
from app.db_depends import get_db


# Создаём маршрутизатор для товаров
router = APIRouter(
    prefix="/products",
    tags=["products"],
)


FILTERS = [
    ("category_id", ProductModel.category_id, eq),
    ("min_price", ProductModel.price, ge),
    ("max_price", ProductModel.price, le),
    ("seller_id", ProductModel.seller_id, eq),
    ("created_at", ProductModel.created_at, le),
]


def build_filters(filters: ProductFilter) -> list:
    all_filters = [ProductModel.is_active]

    if (
        filters.min_price is not None
        and filters.max_price is not None
        and filters.min_price > filters.max_price
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="min_price не может быть больше max_price",
        )

    for param_name, column, op in FILTERS:
        value = getattr(filters, param_name, None)
        if value is not None:
            all_filters.append(op(column, value))
    if filters.in_stock is not None:
        all_filters.append(
            ProductModel.stock > 0 if filters.in_stock else ProductModel.stock == 0
        )
    return all_filters


async def category_by_id(
    category_id: Annotated[int, Path()], db: Annotated[AsyncSession, Depends(get_db)]
) -> Category:
    result = await db.scalars(
        select(Category).where(and_(Category.id == category_id, Category.is_active))
    )
    category: Category | None = result.first()
    if not category:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Category not found or inactive",
        )
    return category


async def product_by_id(
    product_id: Annotated[int, Path()],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(get_current_seller)],
) -> ProductModel:
    result = await db.scalars(
        select(ProductModel).where(
            and_(ProductModel.id == product_id, ProductModel.is_active)
        )
    )
    product = result.first()
    if product.seller_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not the owner of this product",
        )
    if not product:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Product not found or inactive",
        )
    return product


@router.get("/", response_model=ProductList, status_code=status.HTTP_200_OK)
async def get_all_products(
    page: Annotated[int, Query(ge=1)],
    db: Annotated[AsyncSession, Depends(get_db)],
    filters: Annotated[ProductFilter, Depends()],
    page_size: int = Query(3, ge=1, le=100),
    search: str | None = Query(
        None, min_length=1, description="Поиск по названию товара"
    ),
) -> dict[str, Any]:
    """
    Возвращает список всех товаров.
    """

    all_filters = build_filters(filters)

    rank_colummn = None

    if search:
        search_value = search.strip()
        if search_value:
            ts_query = func.websearch_to_tsquery("english", search_value)
            all_filters.append(ProductModel.tsv.op("@@")(ts_query))
            rank_colummn = func.ts_rank_cd(ProductModel.tsv, ts_query).label("rank")

    total = (
        await db.scalar(
            select(func.count()).select_from(ProductModel).where(and_(*all_filters))
        )
        or 0
    )

    if rank_colummn is not None:
        product_stmt = (
            select(ProductModel, rank_colummn)
            .where(and_(*all_filters))
            .order_by(desc(rank_colummn), ProductModel.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        product = await db.execute(product_stmt)
        rows = product.all()
        items = [row[0] for row in rows]
    else:
        result = await db.scalars(
            select(ProductModel)
            .where(and_(*all_filters))
            .order_by(ProductModel.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items: list[ProductModel] = result.all()
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/", response_model=ProductSchema, status_code=status.HTTP_201_CREATED)
async def create_product(
    product: Annotated[ProductCreate, Body()],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(get_current_seller)],
) -> ProductSchema:
    """
    Создаёт новый товар.
    """
    await category_by_id(product.category_id, db=db)
    product = ProductModel(**product.model_dump(), seller_id=current_user.id)
    db.add(product)
    await db.commit()
    await db.refresh(product)
    return product


@router.get(
    "/category/{category_id}",
    response_model=list[ProductSchema],
    status_code=status.HTTP_200_OK,
)
async def get_products_by_category(
    db: Annotated[AsyncSession, Depends(get_db)],
    category: Annotated[Category, Depends(category_by_id)],
) -> list[ProductSchema]:
    """
    Возвращает список товаров в указанной категории по её ID.
    """
    result = await db.scalars(
        select(ProductModel).where(
            and_(ProductModel.category_id == category.id, ProductModel.is_active)
        )
    )
    products = result.all()
    return products


@router.get(
    "/{product_id}/reviews",
    response_model=list[ReviewSchema],
    status_code=status.HTTP_200_OK,
)
async def get_reviews_by_product_id(
    product_id: Annotated[int, Path()], db: Annotated[AsyncSession, Depends(get_db)]
) -> list[ReviewSchema]:
    product = await db.scalar(
        select(ProductModel)
        .options(
            selectinload(ProductModel.reviews),
            with_loader_criteria(ReviewsModel, ReviewsModel.is_active),
        )
        .where(
            ProductModel.id == product_id,
            ProductModel.is_active,
        )
    )
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found or inactive",
        )

    return product.reviews


@router.get(
    "/{product_id}", response_model=ProductSchema, status_code=status.HTTP_200_OK
)
async def get_product(
    product: Annotated[ProductModel, Depends(product_by_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProductSchema:
    """
    Возвращает детальную информацию о товаре по его ID.
    """
    await category_by_id(product.category_id, db)
    return product


@router.put(
    "/{product_id}", response_model=ProductSchema, status_code=status.HTTP_200_OK
)
async def update_product(
    product: Annotated[ProductModel, Depends(product_by_id)],
    new_product: Annotated[ProductCreate, Body()],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProductSchema:
    """
    Обновляет товар по его ID.
    """

    await category_by_id(new_product.category_id, db)
    await db.execute(
        update(ProductModel)
        .where(ProductModel.id == product.id)
        .values(
            **new_product.model_dump(),
        )
    )
    await db.commit()
    await db.refresh(product)
    return product


@router.delete("/{product_id}", status_code=status.HTTP_200_OK)
async def delete_product(
    product: Annotated[ProductModel, Depends(product_by_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Удаляет товар по его ID.
    """
    await db.execute(
        update(ProductModel)
        .where(ProductModel.id == product.id)
        .values(is_active=False)
    )
    await db.commit()
    return {"status": "success", "message": "Product marked as inactive"}
