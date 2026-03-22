"""Qdrant vector store for news articles with sentence-transformer embeddings."""

import os
import json
from datetime import datetime
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct,
    Filter, FieldCondition, MatchValue, MatchAny,
    PayloadSchemaType,
)
from sentence_transformers import SentenceTransformer

from news_collector import Article

# Config
QDRANT_PATH = os.path.join(os.path.dirname(__file__), "qdrant_data")
COLLECTION_NAME = "news_articles"
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
VECTOR_DIM = 384
CHUNK_SIZE = 500  # characters per chunk
CHUNK_OVERLAP = 100

# Singleton instances
_model = None
_client = None


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def get_client() -> QdrantClient:
    global _client
    if _client is None:
        Path(QDRANT_PATH).mkdir(parents=True, exist_ok=True)
        _client = QdrantClient(path=QDRANT_PATH)
    return _client


def ensure_collection():
    """Create collection if it doesn't exist."""
    client = get_client()
    collections = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME not in collections:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
        )
        # Create payload indexes for filtering
        client.create_payload_index(COLLECTION_NAME, "source", PayloadSchemaType.KEYWORD)
        client.create_payload_index(COLLECTION_NAME, "article_id", PayloadSchemaType.KEYWORD)
        client.create_payload_index(COLLECTION_NAME, "categories", PayloadSchemaType.KEYWORD)


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE,
               overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks."""
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size

        # Try to break at sentence boundary
        if end < len(text):
            for sep in [".", "。", "!", "?", "\n"]:
                last_sep = text[start:end].rfind(sep)
                if last_sep > chunk_size * 0.3:
                    end = start + last_sep + 1
                    break

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        start = end - overlap
        if start >= len(text):
            break

    return chunks


def index_articles(articles: list[Article],
                   progress_callback=None) -> dict:
    """Vectorize and store articles in Qdrant."""
    ensure_collection()
    model = get_model()
    client = get_client()

    total = len(articles)
    indexed = 0
    skipped = 0
    total_chunks = 0

    for i, article in enumerate(articles):
        if not article.content or len(article.content.strip()) < 50:
            skipped += 1
            continue

        # Check if already indexed
        existing = client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=Filter(must=[
                FieldCondition(key="article_id", match=MatchValue(value=article.id))
            ]),
            limit=1,
        )
        if existing[0]:
            skipped += 1
            if progress_callback:
                progress_callback(i + 1, total, "skip", article.title)
            continue

        # Chunk the content
        full_text = f"{article.title}\n\n{article.content}"
        chunks = chunk_text(full_text)

        # Generate embeddings for all chunks at once
        embeddings = model.encode(chunks, show_progress_bar=False)

        # Create points
        points = []
        for j, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            point_id = hash(f"{article.id}_{j}") % (2**63)
            if point_id < 0:
                point_id = abs(point_id)

            points.append(PointStruct(
                id=point_id,
                vector=embedding.tolist(),
                payload={
                    "article_id": article.id,
                    "title": article.title,
                    "chunk_text": chunk,
                    "chunk_index": j,
                    "total_chunks": len(chunks),
                    "url": article.url,
                    "source": article.source,
                    "author": article.author,
                    "published": article.published,
                    "collected_at": article.collected_at,
                    "categories": article.categories,
                    "summary": article.summary,
                }
            ))

        # Upsert in batches
        batch_size = 64
        for k in range(0, len(points), batch_size):
            client.upsert(
                collection_name=COLLECTION_NAME,
                points=points[k:k + batch_size],
            )

        indexed += 1
        total_chunks += len(chunks)

        if progress_callback:
            progress_callback(i + 1, total, "done", article.title)

    return {
        "total_articles": total,
        "indexed": indexed,
        "skipped": skipped,
        "total_chunks": total_chunks,
    }


def search(query: str, top_k: int = 10,
           sources: list[str] = None,
           categories: list[str] = None) -> list[dict]:
    """Semantic search over indexed articles."""
    ensure_collection()
    model = get_model()
    client = get_client()

    query_vector = model.encode(query).tolist()

    # Build filter
    must_conditions = []
    if sources:
        must_conditions.append(
            FieldCondition(key="source", match=MatchAny(any=sources))
        )
    if categories:
        must_conditions.append(
            FieldCondition(key="categories", match=MatchAny(any=categories))
        )

    search_filter = Filter(must=must_conditions) if must_conditions else None

    results = client.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        query_filter=search_filter,
        limit=top_k,
        with_payload=True,
    )

    # Deduplicate by article_id, keep highest score
    seen = {}
    for point in results.points:
        aid = point.payload.get("article_id", "")
        score = point.score
        if aid not in seen or score > seen[aid]["score"]:
            seen[aid] = {
                "score": round(score, 4),
                "title": point.payload.get("title", ""),
                "chunk_text": point.payload.get("chunk_text", ""),
                "url": point.payload.get("url", ""),
                "source": point.payload.get("source", ""),
                "published": point.payload.get("published", ""),
                "categories": point.payload.get("categories", []),
                "summary": point.payload.get("summary", ""),
                "article_id": aid,
            }

    results_list = sorted(seen.values(), key=lambda x: x["score"], reverse=True)
    return results_list


def get_stats() -> dict:
    """Get collection statistics."""
    ensure_collection()
    client = get_client()
    info = client.get_collection(COLLECTION_NAME)

    return {
        "total_vectors": info.points_count,
        "status": str(info.status),
        "vector_dim": VECTOR_DIM,
        "model": EMBEDDING_MODEL,
        "storage_path": QDRANT_PATH,
    }


def delete_collection():
    """Delete the entire collection."""
    client = get_client()
    collections = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME in collections:
        client.delete_collection(COLLECTION_NAME)
    return {"success": True, "message": "컬렉션이 삭제되었습니다."}


def get_all_sources() -> list[str]:
    """Get list of all indexed sources."""
    ensure_collection()
    client = get_client()
    try:
        results = client.scroll(
            collection_name=COLLECTION_NAME,
            limit=1000,
            with_payload=["source"],
        )
        sources = set()
        for point in results[0]:
            src = point.payload.get("source")
            if src:
                sources.add(src)
        return sorted(sources)
    except Exception:
        return []


def browse_articles(offset: int = 0, limit: int = 50,
                    source_filter: str = None) -> dict:
    """Browse all indexed articles (deduplicated by article_id)."""
    ensure_collection()
    client = get_client()

    scroll_filter = None
    if source_filter:
        scroll_filter = Filter(must=[
            FieldCondition(key="source", match=MatchValue(value=source_filter))
        ])

    # Scroll through all points
    all_points, next_offset = client.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=scroll_filter,
        limit=10000,
        with_payload=True,
        with_vectors=False,
    )

    # Deduplicate by article_id, aggregate chunk info
    articles = {}
    for point in all_points:
        aid = point.payload.get("article_id", "")
        if aid not in articles:
            articles[aid] = {
                "article_id": aid,
                "title": point.payload.get("title", ""),
                "url": point.payload.get("url", ""),
                "source": point.payload.get("source", ""),
                "published": point.payload.get("published", ""),
                "collected_at": point.payload.get("collected_at", ""),
                "categories": point.payload.get("categories", []),
                "summary": point.payload.get("summary", ""),
                "total_chunks": point.payload.get("total_chunks", 1),
                "chunks": [],
            }
        articles[aid]["chunks"].append({
            "index": point.payload.get("chunk_index", 0),
            "text": point.payload.get("chunk_text", ""),
            "point_id": point.id,
        })

    # Sort chunks within each article
    for a in articles.values():
        a["chunks"].sort(key=lambda c: c["index"])

    # Sort articles by collected_at (newest first)
    sorted_articles = sorted(articles.values(),
                             key=lambda x: x.get("collected_at", ""), reverse=True)

    total = len(sorted_articles)
    page = sorted_articles[offset:offset + limit]

    return {
        "success": True,
        "total_articles": total,
        "offset": offset,
        "limit": limit,
        "articles": page,
    }


def index_intel_briefing(briefing_text: str, ts: str, modules_data: dict = None) -> dict:
    """OSINT 인텔 브리핑 텍스트를 섹션별로 청크 분할 후 벡터 저장."""
    ensure_collection()
    model = get_model()
    client = get_client()

    briefing_id = f"intel_{ts}"
    collected_at = datetime.utcnow().isoformat()

    # 기존 인덱싱 여부 확인
    existing = client.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=Filter(must=[
            FieldCondition(key="article_id", match=MatchValue(value=briefing_id))
        ]),
        limit=1,
    )
    if existing[0]:
        return {"indexed": 0, "skipped": 1, "total_chunks": 0}

    # 마크다운을 H2 섹션 단위로 분리
    sections = []
    current_title = f"OSINT 인텔 브리핑 {ts}"
    current_lines = []

    for line in briefing_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            if current_lines:
                sections.append((current_title, "\n".join(current_lines).strip()))
            current_title = stripped[3:].strip()
            current_lines = []
        elif stripped.startswith("# "):
            current_title = stripped[2:].strip()
        else:
            current_lines.append(line)

    if current_lines:
        sections.append((current_title, "\n".join(current_lines).strip()))

    # 섹션이 없으면 전체를 하나로
    if not sections:
        sections = [(f"OSINT 인텔 브리핑 {ts}", briefing_text)]

    # 모듈별 카테고리 매핑 키워드
    section_category_map = {
        "항공": "aviation", "aviation": "aviation",
        "해상": "maritime", "maritime": "maritime", "naval": "maritime",
        "분쟁": "conflicts", "conflict": "conflicts",
        "열점": "thermal", "thermal": "thermal",
        "원자재": "commodity", "commodity": "commodity",
        "환율": "forex", "forex": "forex",
        "물류": "logistics", "logistics": "logistics",
        "요점": "summary", "executive": "summary",
    }

    total_chunks = 0
    all_points = []
    chunk_global_idx = 0

    for sec_idx, (sec_title, sec_text) in enumerate(sections):
        if not sec_text or len(sec_text.strip()) < 20:
            continue

        # 섹션 카테고리 감지
        cat = "intel"
        for kw, mapped in section_category_map.items():
            if kw in sec_title.lower():
                cat = mapped
                break

        full_text = f"{sec_title}\n\n{sec_text}"
        chunks = chunk_text(full_text)
        embeddings = model.encode(chunks, show_progress_bar=False)

        for j, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            point_id = abs(hash(f"{briefing_id}_s{sec_idx}_c{j}")) % (2**63)
            all_points.append(PointStruct(
                id=point_id,
                vector=embedding.tolist(),
                payload={
                    "article_id": briefing_id,
                    "title": sec_title,
                    "chunk_text": chunk,
                    "chunk_index": chunk_global_idx,
                    "total_chunks": 0,  # 나중에 채움
                    "url": "",
                    "source": "KSPD-OSINT",
                    "author": "KSPD OSINT System",
                    "published": collected_at,
                    "collected_at": collected_at,
                    "categories": ["intel", cat],
                    "summary": sec_text[:200] if len(sec_text) > 200 else sec_text,
                    "intel_section": sec_title,
                    "intel_ts": ts,
                }
            ))
            chunk_global_idx += 1

        total_chunks += len(chunks)

    # total_chunks 업데이트 후 upsert
    for p in all_points:
        p.payload["total_chunks"] = chunk_global_idx

    batch_size = 64
    for k in range(0, len(all_points), batch_size):
        client.upsert(
            collection_name=COLLECTION_NAME,
            points=all_points[k:k + batch_size],
        )

    return {
        "indexed": 1,
        "skipped": 0,
        "total_chunks": total_chunks,
        "sections": len(sections),
        "briefing_id": briefing_id,
    }


def get_article_detail(article_id: str) -> dict:
    """Get full detail of a single article with all chunks."""
    ensure_collection()
    client = get_client()

    results, _ = client.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=Filter(must=[
            FieldCondition(key="article_id", match=MatchValue(value=article_id))
        ]),
        limit=1000,
        with_payload=True,
        with_vectors=True,
    )

    if not results:
        return {"success": False, "error": "기사를 찾을 수 없습니다."}

    first = results[0].payload
    chunks = []
    for point in results:
        chunks.append({
            "index": point.payload.get("chunk_index", 0),
            "text": point.payload.get("chunk_text", ""),
            "point_id": point.id,
            "vector_preview": point.vector[:8] if point.vector else [],
        })
    chunks.sort(key=lambda c: c["index"])

    return {
        "success": True,
        "article": {
            "article_id": article_id,
            "title": first.get("title", ""),
            "url": first.get("url", ""),
            "source": first.get("source", ""),
            "published": first.get("published", ""),
            "collected_at": first.get("collected_at", ""),
            "categories": first.get("categories", []),
            "summary": first.get("summary", ""),
            "total_chunks": len(chunks),
            "chunks": chunks,
            "full_text": "\n".join(c["text"] for c in chunks),
        }
    }
