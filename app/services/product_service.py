"""
Product Service - Handles product tracking, fuzzy matching, and Tamil translation
"""
import asyncio
from datetime import datetime
from typing import List, Optional, Dict
import os
import httpx
from app.config.database import get_database
from app.config.logging_config import get_logger

logger = get_logger(__name__)


class ProductService:
    """Service for product management and tracking"""
    
    def __init__(self):
        self.db = None
        self.tamil_agent_id = os.getenv("LYZR_TAMIL_AGENT_ID", "695e1e0252ab53b7bf377caa")
        self.api_key = os.getenv("LYZR_API_KEY") or os.getenv("Lyzr_API_KEY")
        self.api_url = os.getenv("LYZR_API_URL", "https://studio.lyzr.ai")
        logger.info(f"ProductService initialized with Tamil Agent: {self.tamil_agent_id}")
    
    def _get_db(self):
        """Get database connection lazily"""
        if self.db is None:
            self.db = get_database()
        return self.db
    
    def get_all_products(self) -> List[dict]:
        """Get all products from Top_Products collection"""
        try:
            db = self._get_db()
            products = list(db.Top_Products.find({}))
            for p in products:
                p["_id"] = str(p["_id"])
            logger.info(f"📦 Retrieved {len(products)} products from Top_Products")
            return products
        except Exception as e:
            logger.error(f"❌ Error fetching products: {e}", exc_info=True)
            return []
    
    def get_product_stats(self) -> dict:
        """Get product stats for dashboard"""
        try:
            db = self._get_db()
            products = list(db.Top_Products.find({}))
            
            stats = {
                "totalProducts": len(products),
                "productRecommendationTotal": sum(p.get("productRecommendationCount", 0) for p in products),
                "salesPitchTotal": sum(p.get("salesPitchCount", 0) for p in products),
                "products": []
            }
            
            for p in products:
                stats["products"].append({
                    "_id": str(p["_id"]),
                    "productName": p.get("productName", ""),
                    "productNameTamil": p.get("productNameTamil", ""),
                    "productRecommendationCount": p.get("productRecommendationCount", 0),
                    "salesPitchCount": p.get("salesPitchCount", 0),
                    "updatedAt": p.get("updatedAt")
                })
            
            return stats
        except Exception as e:
            logger.error(f"❌ Error getting product stats: {e}", exc_info=True)
            return {"totalProducts": 0, "productRecommendationTotal": 0, "salesPitchTotal": 0, "products": []}
    
    def fuzzy_match_product(self, text: str, product_name: str, min_match_ratio: float = 0.6) -> bool:
        """
        Check if product name words exist in text (flexible matching)
        - Words can be in any order (jumbled)
        - Partial match allowed (at least min_match_ratio of product words must match)
        - Works with English and Tamil
        
        Example: "Star Health Assure Insurance Policy" matches:
        - "Star Health Assure" (exact)
        - "Assure Star Health" (jumbled)
        - "Star Assure" (partial - 2 of 3 words = 66%)
        """
        if not text or not product_name:
            return False
        
        import re
        
        # SIMPLE CHECK FIRST: Direct substring match (case-insensitive)
        if product_name.lower() in text.lower():
            logger.debug(f"✅ Direct match: '{product_name}' found in text")
            return True
        
        # Normalize: lowercase, remove extra spaces and punctuation
        # Keep Tamil characters (Unicode range \u0B80-\u0BFF for Tamil)
        text_clean = re.sub(r'[^\w\s\u0B80-\u0BFF]', ' ', text.lower())
        product_clean = re.sub(r'[^\w\s\u0B80-\u0BFF]', ' ', product_name.lower())
        
        text_words = set(text_clean.split())
        product_words = set(product_clean.split())
        
        # Remove common filler words that might cause false negatives
        filler_words = {
            'the', 'a', 'an', 'for', 'of', 'and', 'or', 'with', 'to', 'in', 'on',
            'is', 'are', 'was', 'were', 'be', 'been', 'being', 'this', 'that',
            'policy', 'insurance', 'plan', 'cover', 'coverage'  # Common insurance terms
        }
        product_words_filtered = product_words - filler_words
        
        if not product_words_filtered:
            # If all words were filler words, use original set
            product_words_filtered = product_words
        
        if not product_words_filtered:
            return False
        
        # Count how many product words are in the text
        matched_words = product_words_filtered.intersection(text_words)
        match_ratio = len(matched_words) / len(product_words_filtered)
        
        # Also check for partial word matches (e.g., "comprehensive" matches "comprehensive insurance")
        if match_ratio < min_match_ratio:
            # Try substring matching for remaining unmatched words
            unmatched = product_words_filtered - matched_words
            for pw in unmatched:
                if len(pw) >= 4:  # Only check words >= 4 chars
                    for tw in text_words:
                        if pw in tw or tw in pw:
                            matched_words.add(pw)
                            break
            match_ratio = len(matched_words) / len(product_words_filtered)
        
        match = match_ratio >= min_match_ratio
        
        if match:
            logger.debug(f"✅ Fuzzy match: '{product_name}' (ratio: {match_ratio:.2f}, words: {matched_words})")
        
        return match
    
    def find_products_in_text(self, text: str) -> List[dict]:
        """
        Find all products mentioned in text.
        Uses a priority-based matching approach:
        1. FIRST: Check for exact keyword matches (highest priority)
        2. SECOND: Check for direct product name or core phrase match
        3. THIRD: Fuzzy matching (lowest priority, stricter threshold)
        
        This reduces false positives from generic words like "star", "health".
        """
        if not text or len(text.strip()) < 5:
            return []
            
        products = self.get_all_products()
        found = []
        found_ids = set()  # Track found product IDs to avoid duplicates
        text_lower = text.lower()
        
        logger.info(f"🔍 Scanning text for {len(products)} products...")
        logger.info(f"   Text length: {len(text)} chars")
        
        for product in products:
            product_id = product.get("_id")
            if product_id in found_ids:
                continue
                
            product_name = product.get("productName", "")
            
            # PRIORITY 1: Check keywords FIRST (most precise)
            # Only use keywords that are distinctive enough (min 8 chars)
            matched_by_keyword = False
            for keyword in product.get("keywords", []):
                if keyword and len(keyword) >= 8:  # Require min 8 chars to avoid generic matches
                    # Use word boundary matching for better precision
                    import re
                    # Create pattern that matches keyword as standalone words
                    pattern = r'\b' + re.escape(keyword.lower()) + r'\b'
                    if re.search(pattern, text_lower):
                        logger.info(f"✅ Found product via KEYWORD: '{keyword}' -> {product_name}")
                        found.append(product)
                        found_ids.add(product_id)
                        matched_by_keyword = True
                        break
            
            if matched_by_keyword:
                continue
            
            # PRIORITY 2: Check exact product name match
            if product_name.lower() in text_lower:
                logger.info(f"✅ Found product via EXACT NAME: {product_name}")
                found.append(product)
                found_ids.add(product_id)
                continue
            
            # PRIORITY 2b: Check for core phrase match
            # Extract unique identifying words (exclude generic terms)
            core_words = [w for w in product_name.split() 
                         if len(w) > 3 and w.lower() not in 
                         {'star', 'health', 'insurance', 'policy', 'plan', 'care', 'cover', 'the'}]
            
            if len(core_words) >= 2:
                # Need at least 2 core words to match
                core_phrase = ' '.join(core_words)
                if core_phrase.lower() in text_lower:
                    logger.info(f"✅ Found product via CORE PHRASE: '{core_phrase}' -> {product_name}")
                    found.append(product)
                    found_ids.add(product_id)
                    continue
            
            # PRIORITY 3: Check Tamil name (direct match)
            tamil_name = product.get("productNameTamil", "")
            if tamil_name and tamil_name in text:
                logger.info(f"✅ Found product via TAMIL NAME: {tamil_name} -> {product_name}")
                found.append(product)
                found_ids.add(product_id)
                continue
            
            # NOTE: Fuzzy matching disabled - too many false positives with generic words
            # The keyword matching above is more reliable
        
        if found:
            logger.info(f"🔍 Total products found: {len(found)}")
            for p in found:
                logger.info(f"   - {p.get('productName')}")
        else:
            logger.info(f"🔍 No products found in text (searched {len(products)} products)")
        
        return found
    
    def track_product_mention(self, session_id: str, product_id: str, agent_type: str) -> bool:
        """
        Increment product count (only once per conversation/session)
        
        Args:
            session_id: Conversation session ID
            product_id: Product document ID
            agent_type: 'product_recommendation' or 'sales_pitch'
        
        Returns:
            True if count was incremented, False if already tracked
        """
        try:
            db = self._get_db()
            from bson import ObjectId
            
            # Check if already tracked for this session
            existing = db.ProductTraces.find_one({
                "sessionId": session_id,
                "productId": product_id
            })
            
            if existing:
                logger.debug(f"📌 Product already tracked for session: {session_id[:12]}...")
                return False
            
            # Create trace record
            now = datetime.utcnow()
            db.ProductTraces.insert_one({
                "sessionId": session_id,
                "productId": product_id,
                "agentType": agent_type,
                "createdAt": now
            })
            
            # Increment appropriate counter
            field = "productRecommendationCount" if agent_type == "product_recommendation" else "salesPitchCount"
            db.Top_Products.update_one(
                {"_id": ObjectId(product_id)},
                {
                    "$inc": {field: 1},
                    "$set": {"updatedAt": now}
                }
            )
            
            logger.info(f"✅ Product tracked: {product_id[:12]}... ({agent_type})")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error tracking product: {e}", exc_info=True)
            return False
    
    async def track_products_in_response(self, response_text: str, session_id: str, agent_type: str):
        """
        Background task to scan agent response for product mentions and track them.
        Called for EVERY agent message to ensure products are tracked.
        """
        try:
            logger.info(f"=" * 60)
            logger.info(f"📦 PRODUCT TRACKING STARTED")
            logger.info(f"   Session: {session_id[:20]}...")
            logger.info(f"   Agent Type: {agent_type}")
            logger.info(f"   Response Length: {len(response_text)} chars")
            logger.info(f"   Response Preview: {response_text[:200]}...")
            logger.info(f"=" * 60)
            
            found_products = self.find_products_in_text(response_text)
            
            logger.info(f"🔍 Products found: {len(found_products)}")
            
            if not found_products:
                logger.info(f"⚠️ No products found in agent response")
                # Log what products we have in the database for comparison
                all_products = self.get_all_products()
                logger.debug(f"   Available products ({len(all_products)}): {[p.get('productName')[:30] for p in all_products[:5]]}...")
            else:
                tracked_count = 0
                for product in found_products:
                    product_id = product.get("_id")
                    product_name = product.get("productName", "Unknown")
                    
                    logger.info(f"📝 Tracking product: {product_name}")
                    logger.info(f"   Product ID: {product_id}")
                    
                    if product_id:
                        success = self.track_product_mention(session_id, str(product_id), agent_type)
                        if success:
                            tracked_count += 1
                            logger.info(f"   ✅ Successfully tracked!")
                        else:
                            logger.info(f"   📌 Already tracked for this session")
                    else:
                        logger.warning(f"   ⚠️ Product ID is missing!")
                
                logger.info(f"📊 Tracking Summary: {tracked_count} new, {len(found_products) - tracked_count} already tracked")
                
        except Exception as e:
            logger.error(f"❌ Error in product tracking: {e}", exc_info=True)
    
    async def translate_to_tamil(self, english_text: str) -> str:
        """
        Call Lyzr Tamil Agent for English to Tamil translation
        Uses the same endpoint pattern as other Lyzr agents
        """
        if not english_text:
            return ""
        
        try:
            import uuid
            # Use the same production endpoint as other Lyzr agents
            endpoint_url = "https://agent-prod.studio.lyzr.ai/v3/inference/chat/"
            session_id = f"translate-{uuid.uuid4()}"
            
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    endpoint_url,
                    json={
                        "user_id": "translator",
                        "agent_id": self.tamil_agent_id,
                        "session_id": session_id,
                        "message": english_text
                    },
                    headers={
                        "Content-Type": "application/json",
                        "x-api-key": self.api_key
                    }
                )
                
                if response.status_code == 200:
                    data = response.json()
                    tamil_text = data.get("response", english_text)
                    logger.info(f"✅ Translated to Tamil: {tamil_text[:50]}...")
                    return tamil_text
                else:
                    logger.error(f"❌ Tamil translation failed: {response.status_code}")
                    logger.error(f"   Response: {response.text[:200] if response.text else 'No response'}")
                    return english_text
                    
        except Exception as e:
            logger.error(f"❌ Error translating to Tamil: {e}", exc_info=True)
            return english_text
    
    async def generate_product_keywords(self, product_name: str) -> dict:
        """
        Generate product keywords/variations using Lyzr agent.
        Returns both English and Tamil variations.
        
        Args:
            product_name: Product name in English (e.g., "Star Health Assure Insurance Policy")
        
        Returns:
            dict with keys:
            - tamil_name: Tamil translation of the product name
            - english_keywords: List of English variations
            - tamil_keywords: List of Tamil variations
        """
        result = {
            "tamil_name": "",
            "english_keywords": [],
            "tamil_keywords": []
        }
        
        if not product_name:
            return result
        
        try:
            import uuid
            import json
            import re
            
            endpoint_url = "https://agent-prod.studio.lyzr.ai/v3/inference/chat/"
            session_id = f"keywords-{uuid.uuid4()}"
            
            # Prompt for generating keywords
            prompt = f"""Generate product name variations for this Star Health insurance product:
"{product_name}"

Return a JSON object with:
1. "tamil_name": The full product name translated to Tamil
2. "english_keywords": Array of 4-6 SHORT English variations/aliases (e.g., "Star Assure", "Health Assure")
3. "tamil_keywords": Array of 2-3 SHORT Tamil variations

Rules:
- Keywords should be SHORT (2-4 words max)
- Remove words like "Insurance Policy" from keywords
- Keep distinct/unique parts of the name
- Tamil keywords should be common short forms

Example output for "Star Women Care Insurance Policy":
{{
    "tamil_name": "ஸ்டார் பெண்கள் பராமரிப்பு காப்பீட்டு",
    "english_keywords": ["Star Women Care", "Women Care", "Star Women", "Women Care Policy"],
    "tamil_keywords": ["ஸ்டார் விமன் கேர்", "விமன் கேர்"]
}}

Return ONLY the JSON, no other text."""

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    endpoint_url,
                    json={
                        "user_id": "keyword_generator",
                        "agent_id": self.tamil_agent_id,
                        "session_id": session_id,
                        "message": prompt
                    },
                    headers={
                        "Content-Type": "application/json",
                        "x-api-key": self.api_key
                    }
                )
                
                if response.status_code == 200:
                    data = response.json()
                    response_text = data.get("response", "")
                    
                    # Try to parse JSON from response
                    try:
                        # Extract JSON from response (might be wrapped in markdown)
                        json_match = re.search(r'\{[\s\S]*\}', response_text)
                        if json_match:
                            keywords_data = json.loads(json_match.group())
                            result["tamil_name"] = keywords_data.get("tamil_name", "")
                            result["english_keywords"] = keywords_data.get("english_keywords", [])
                            result["tamil_keywords"] = keywords_data.get("tamil_keywords", [])
                            logger.info(f"✅ Generated keywords for '{product_name}':")
                            logger.info(f"   Tamil name: {result['tamil_name']}")
                            logger.info(f"   English keywords: {result['english_keywords']}")
                            logger.info(f"   Tamil keywords: {result['tamil_keywords']}")
                        else:
                            logger.warning(f"⚠️ Could not parse JSON from response, using fallback")
                            result["tamil_name"] = await self.translate_to_tamil(product_name)
                    except json.JSONDecodeError as e:
                        logger.warning(f"⚠️ JSON parse error: {e}, using fallback")
                        result["tamil_name"] = await self.translate_to_tamil(product_name)
                else:
                    logger.error(f"❌ Keyword generation failed: {response.status_code}")
                    # Fallback to simple translation
                    result["tamil_name"] = await self.translate_to_tamil(product_name)
                    
        except Exception as e:
            logger.error(f"❌ Error generating keywords: {e}", exc_info=True)
            # Fallback to simple translation
            result["tamil_name"] = await self.translate_to_tamil(product_name)
        
        # Generate basic English variations as fallback if none were generated
        if not result["english_keywords"]:
            result["english_keywords"] = self._generate_basic_variations(product_name)
        
        return result
    
    def _generate_basic_variations(self, product_name: str) -> list:
        """
        Generate basic product name variations locally (fallback).
        Removes common insurance terms to create short variations.
        """
        variations = []
        
        if not product_name:
            return variations
        
        # Remove common suffixes
        base_name = product_name
        for suffix in ["Insurance Policy", "Policy", "Insurance", "Plan"]:
            if base_name.endswith(suffix):
                base_name = base_name[:-len(suffix)].strip()
        
        # Add the base name (without suffix)
        if base_name and base_name != product_name:
            variations.append(base_name)
        
        # Split into words and create combinations
        words = base_name.split()
        
        # Remove "Star" and "Health" to find unique identifiers
        unique_words = [w for w in words if w.lower() not in ['star', 'health', 'insurance', 'policy', 'plan', '&']]
        
        if len(unique_words) >= 1:
            # Add unique words with "Star"
            variations.append(f"Star {' '.join(unique_words)}")
            
            # Add just the unique words
            if len(unique_words) >= 2:
                variations.append(' '.join(unique_words))
        
        return list(set(variations))  # Remove duplicates
    
    def _get_existing_keywords(self) -> set:
        """Get all existing keywords from all products to avoid duplicates"""
        try:
            db = self._get_db()
            products = list(db.Top_Products.find({}, {"keywords": 1}))
            all_keywords = set()
            for p in products:
                for kw in p.get("keywords", []):
                    all_keywords.add(kw.lower().strip())
            return all_keywords
        except Exception as e:
            logger.warning(f"⚠️ Could not get existing keywords: {e}")
            return set()
    
    def _filter_unique_keywords(self, keywords: list, existing: set) -> list:
        """Filter out keywords that already exist for other products"""
        unique = []
        for kw in keywords:
            if kw.lower().strip() not in existing:
                unique.append(kw)
            else:
                logger.debug(f"   Skipping duplicate keyword: {kw}")
        return unique
    
    async def add_product(self, product_name_english: str) -> Optional[dict]:
        """
        Add a new product with auto-generated Tamil translation and keywords.
        """
        if not product_name_english:
            return None
            
        product_name_english = product_name_english.strip()
        
        try:
            db = self._get_db()
            
            # 🔒 UNIQUE CHECK: Case-insensitive check for product name
            import re
            existing = db.Top_Products.find_one({
                "productName": re.compile(f"^{re.escape(product_name_english)}$", re.IGNORECASE)
            })
            
            if existing:
                logger.warning(f"⚠️ Product already exists (case-insensitive): {product_name_english}")
                existing["_id"] = str(existing["_id"])
                existing["already_exists"] = True
                return existing
            
            # Get existing keywords to avoid duplicates
            existing_keywords = self._get_existing_keywords()
            
            # Generate keywords using Lyzr agent
            logger.info(f"🔄 Generating keywords for: {product_name_english}")
            keywords_data = await self.generate_product_keywords(product_name_english)
            
            # Combine all keywords
            all_keywords = []
            
            # Add Tamil name as keyword
            if keywords_data["tamil_name"]:
                all_keywords.append(keywords_data["tamil_name"])
            
            # Add English keywords (filtered for uniqueness)
            unique_english = self._filter_unique_keywords(
                keywords_data["english_keywords"], 
                existing_keywords
            )
            all_keywords.extend(unique_english)
            
            # Add Tamil keywords (filtered for uniqueness)
            unique_tamil = self._filter_unique_keywords(
                keywords_data["tamil_keywords"], 
                existing_keywords
            )
            all_keywords.extend(unique_tamil)
            
            # Remove duplicates
            all_keywords = list(set(all_keywords))
            
            now = datetime.utcnow()
            product_doc = {
                "productName": product_name_english,
                "productNameTamil": keywords_data["tamil_name"],
                "productRecommendationCount": 0,
                "salesPitchCount": 0,
                "keywords": all_keywords,
                "createdAt": now,
                "updatedAt": now
            }
            
            result = db.Top_Products.insert_one(product_doc)
            product_doc["_id"] = str(result.inserted_id)
            
            logger.info(f"✅ Product added: {product_name_english}")
            logger.info(f"   Tamil: {keywords_data['tamil_name']}")
            logger.info(f"   Keywords ({len(all_keywords)}): {all_keywords[:5]}...")
            
            return product_doc
            
        except Exception as e:
            logger.error(f"❌ Error adding product: {e}", exc_info=True)
            return None
    
    def delete_product(self, product_id: str) -> bool:
        """
        Delete a product by ID.
        Also performs CASCADING DELETE on ProductTraces collection.
        """
        try:
            db = self._get_db()
            from bson import ObjectId
            
            logger.info(f"🗑️ Deleting product {product_id} and all its traces...")
            
            # 1. Delete the product itself
            result = db.Top_Products.delete_one({"_id": ObjectId(product_id)})
            
            if result.deleted_count > 0:
                # 2. 🔒 CASCADING DELETE: Remove all mentions of this product in traces
                trace_delete_result = db.ProductTraces.delete_many({"productId": product_id})
                logger.info(f"✅ Product deleted: {product_id}")
                logger.info(f"✅ Also deleted {trace_delete_result.deleted_count} product traces")
                return True
            else:
                logger.warning(f"⚠️ Product not found in database: {product_id}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error in delete_product: {e}", exc_info=True)
            return False


# Singleton instance
_product_service = None

def get_product_service() -> ProductService:
    """Get singleton ProductService instance"""
    global _product_service
    if _product_service is None:
        _product_service = ProductService()
    return _product_service
