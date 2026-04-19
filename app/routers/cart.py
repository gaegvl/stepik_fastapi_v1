from decimal import Decimal
from fastapi import Body, Depends, APIRouter, HTTPException, Response, status, Path
from typing import Annotated
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload
from app.auth import get_current_user
from app.db_depends import get_db

from app.models.users import User as UserModel
from app.models.products import Product as ProductModel
from app.models.cart_items import CartItem as CartItemModel

from app.schemas import (
    Cart as CartSchema,
    CartItem as CartItemSchema,
    CartItemCreate,
    CartItemUpdate,
)

router = APIRouter(prefix="/cart", tags=["cart"])


async def _ensure_producat_available(
    db: Annotated[AsyncSession, Depends(get_db)], product_id: Annotated[int, Path()]
) -> None:
    product = await db.scalar(
        select(ProductModel).where(
            ProductModel.is_active, ProductModel.id == product_id
        )
    )
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found or inactive",
        )


async def _getcart_item(
    db: Annotated[AsyncSession, Depends(get_db)],
    user_id: Annotated[int, Path()],
    product_id: Annotated[int, Path()],
) -> CartItemModel | None:
    result = await db.scalar(
        select(CartItemModel)
        .options(selectinload(CartItemModel.product))
        .where(CartItemModel.user_id == user_id, CartItemModel.product_id == product_id)
    )
    return result


@router.get("/", response_model=CartSchema)
async def get_cart(
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    result = await db.scalars(
        select(CartItemModel)
        .options(selectinload(CartItemModel.product))
        .where(CartItemModel.user_id == current_user.id)
        .order_by(CartItemModel.id)
    )
    items = result.all()

    total_quantity = sum(item.quantity for item in items)
    price_items = (
        Decimal(item.quantity)
        * (item.product.price if item.product.price is not None else Decimal("0"))
        for item in items
    )
    total_price_decimal = sum(price_items, Decimal("0.00"))

    return CartSchema(
        user_id=current_user.id,
        items=items,
        total_quantity=total_quantity,
        total_price=total_price_decimal,
    )


@router.post(
    "/items", response_model=CartItemSchema, status_code=status.HTTP_201_CREATED
)
async def add_item_to_cart(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(get_current_user)],
    payload: Annotated[CartItemCreate, Body()],
) -> CartItemSchema:
    await _ensure_producat_available(db, payload.product_id)

    cart_item = await _getcart_item(db, current_user.id, payload.product_id)
    if cart_item:
        cart_item.quantity += payload.quantity
    else:
        cart_item = CartItemModel(
            user_id=current_user.id,
            product_id=payload.product_id,
            quantity=payload.quantity,
        )
        db.add(cart_item)
    await db.commit()
    updated_item = await _getcart_item(db, current_user.id, payload.product_id)
    return updated_item


@router.put(
    "/items/{product_id}", response_model=CartItemSchema, status_code=status.HTTP_200_OK
)
async def update_cart_item(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(get_current_user)],
    product_id: Annotated[int, Path()],
    payload: Annotated[CartItemUpdate, Body()],
) -> CartItemSchema:
    await _ensure_producat_available(db, product_id)

    cart_item = await _getcart_item(db, current_user.id, product_id)

    if not cart_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Cart item not found"
        )

    cart_item.quantity = payload.quantity

    await db.commit()
    updated_item = await _getcart_item(db, current_user.id, product_id)
    return updated_item


@router.delete("/items/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_item_form_cart(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(get_current_user)],
    product_id: Annotated[int, Path()],
) -> Response:
    item_cart = await _getcart_item(db, current_user.id, product_id)

    if not item_cart:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Cart item not found"
        )

    await db.delete(item_cart)
    await db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/", status_code=status.HTTP_204_NO_CONTENT)
async def clear_cart(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(get_current_user)],
) -> Response:
    await db.execute(
        delete(CartItemModel).where(CartItemModel.user_id == current_user.id)
    )
    await db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
