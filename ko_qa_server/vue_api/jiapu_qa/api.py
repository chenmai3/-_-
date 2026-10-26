from fastapi import APIRouter, Request

from .service import (
    handle_extract_tri,
    handle_extract_triplets,
    handle_get_stage,
    handle_judge_yitu,
    handle_ko_kg_mul_qa,
    handle_ko_kg_mul_qa_check,
    handle_ko_kg_mul_qa_stream,
    handle_merge_ans,
    handle_merge_ans_mul,
    handle_normal_ans,
    handle_split_chenshu_wenti,
    handle_split_chenshu_wenti_json,
)
from .external_sources import handle_get_by_web, handle_hpt_answer, handle_hpt_result


router = APIRouter(prefix="/jiapu_qa", tags=["jiapu_qa.vue"])


@router.post("/judgeYitu")
async def judge_yitu(request: Request):
    return await handle_judge_yitu(request)


@router.post("/splitChenshuWenti")
async def split_chenshu_wenti(request: Request):
    return await handle_split_chenshu_wenti(request)


@router.post("/splitChenshuWentiJSON")
async def split_chenshu_wenti_json(request: Request):
    return await handle_split_chenshu_wenti_json(request)


@router.post("/extract_tri")
async def extract_tri(request: Request):
    return await handle_extract_tri(request)


@router.post("/extract_triplets")
async def extract_triplets(request: Request):
    return await handle_extract_triplets(request)


@router.post("/mergeAns")
async def merge_ans(request: Request):
    return await handle_merge_ans(request)


@router.post("/mergeAnsMul")
async def merge_ans_mul(request: Request):
    return await handle_merge_ans_mul(request)


@router.post("/normalAns")
async def normal_ans(request: Request):
    return await handle_normal_ans(request)


@router.post("/getByWeb")
async def get_by_web(request: Request):
    return await handle_get_by_web(await request.json())


@router.post("/getHuaPUDaMoXingAnswer")
async def get_huaputong_answer(request: Request):
    return await handle_hpt_answer(await request.json())


@router.get("/getHPTById")
async def get_hpt_by_id(queryID: str):
    return await handle_hpt_result(queryID)


@router.post("/ko_kg_mul_qa")
async def ko_kg_mul_qa(request: Request):
    return await handle_ko_kg_mul_qa(request)


@router.post("/ko_kg_mul_qa_stream")
async def ko_kg_mul_qa_stream(request: Request):
    return await handle_ko_kg_mul_qa_stream(request)


@router.post("/getStage")
async def get_stage(request: Request):
    return await handle_get_stage(request)


@router.post("/ko_kg_mul_qa_check")
async def ko_kg_mul_qa_check(request: Request):
    return await handle_ko_kg_mul_qa_check(request)
