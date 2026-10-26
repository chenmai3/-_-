from fastapi import APIRouter, Request

from .graph_construct.api import router as graph_construct_router
from .general_qa.api import router as general_qa_router
from .jiapu_qa.api import router as jiapu_qa_router
from .kdzn_hciqa.api import router as kdzn_hciqa_router
from .rule_construct.api import router as rule_construct_router
from .rule_construct.graph_match import handle_neo4j_query


vue_api_router = APIRouter(prefix="/api", tags=["vue-api"])
vue_api_router.include_router(kdzn_hciqa_router)
vue_api_router.include_router(jiapu_qa_router)
vue_api_router.include_router(graph_construct_router)
vue_api_router.include_router(rule_construct_router)
vue_api_router.include_router(general_qa_router)


@vue_api_router.post("/neo4j_query")
async def neo4j_query(request: Request):
    return await handle_neo4j_query(await request.json())
