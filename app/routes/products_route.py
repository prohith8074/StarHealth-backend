"""
Products routes - API endpoints for product management
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from app.services.product_service import get_product_service
from app.config.logging_config import get_logger

router = APIRouter()
logger = get_logger(__name__)


class ProductCreate(BaseModel):
    productName: str


class ProductResponse(BaseModel):
    _id: str
    productName: str
    productNameTamil: str
    productRecommendationCount: int
    salesPitchCount: int


@router.get("")
async def get_all_products():
    """Get all products from Top_Products collection"""
    logger.info("📦 Fetching all products")
    try:
        product_service = get_product_service()
        products = product_service.get_all_products()
        return {"success": True, "products": products, "count": len(products)}
    except Exception as e:
        logger.error(f"❌ Error fetching products: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch products")


@router.get("/stats")
async def get_product_stats():
    """Get product statistics for dashboard charts"""
    logger.info("📊 Fetching product stats")
    try:
        product_service = get_product_service()
        stats = product_service.get_product_stats()
        return {"success": True, **stats}
    except Exception as e:
        logger.error(f"❌ Error fetching product stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch product stats")


@router.post("")
async def add_product(product: ProductCreate):
    """
    Add a new product
    - Accepts English product name
    - Auto-translates to Tamil using Lyzr Tamil Agent
    """
    logger.info(f"➕ Adding product: {product.productName}")
    try:
        product_service = get_product_service()
        created_product = await product_service.add_product(product.productName)
        
        if created_product:
            return {"success": True, "product": created_product}
        else:
            raise HTTPException(status_code=500, detail="Failed to create product")
            
    except Exception as e:
        logger.error(f"❌ Error adding product: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to add product")


@router.delete("/{product_id}")
async def delete_product(product_id: str):
    """Delete a product by ID"""
    logger.info(f"🗑️ Deleting product: {product_id}")
    try:
        product_service = get_product_service()
        success = product_service.delete_product(product_id)
        
        if success:
            return {"success": True, "message": "Product deleted"}
        else:
            raise HTTPException(status_code=404, detail="Product not found")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error deleting product: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete product")
