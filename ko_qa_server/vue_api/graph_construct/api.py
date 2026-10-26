from fastapi import APIRouter, File, Form, Request, UploadFile

from .file_analysis import (
    handle_analysis_progress,
    handle_analysis_result,
    handle_enter_data_with_file,
    handle_save_analysis_file,
    handle_save_analysis_and_enter_data,
)
from .graph_data import (
    handle_delete_kdzn_test_data,
    handle_get_scene_entities,
    handle_insert_new_rule,
)
from .permissions import (
    handle_get_koqascenarios_with_permission,
    handle_get_koqatheme_with_permission,
)
from ..rule_construct.graph_match import handle_neo4j_query


router = APIRouter(prefix="/graph", tags=["graph_construct.vue"])


@router.post("/save_analysis_and_enterData")
async def save_analysis_and_enter_data(
    userId: str = Form(...),
    file: UploadFile = File(...),
    selectedMainTopic: str = Form("默认主题"),
):
    return await handle_save_analysis_and_enter_data(userId, file, selectedMainTopic)


@router.get("/analysis_progress/{task_id}")
async def analysis_progress(task_id: str):
    return await handle_analysis_progress(task_id)


@router.get("/analysis_result/{task_id}")
async def analysis_result(task_id: str):
    return await handle_analysis_result(task_id)


@router.post("/save_analysisFile")
async def save_analysis_file(
    userId: str = Form(...),
    file: UploadFile = File(...),
):
    return await handle_save_analysis_file(userId, file)


@router.post("/enterDataWithFile")
async def enter_data_with_file(request: Request):
    return await handle_enter_data_with_file(await request.json())


# @router.post("/insert_new_rule")
@router.post("/insert_graph")
async def insert_new_rule(request: Request):
    return await handle_insert_new_rule(request)


@router.post("/delete_kdzn_test_data")
async def delete_kdzn_test_data(request: Request):
    return await handle_delete_kdzn_test_data(request)


@router.post("/get_scene_entities")
async def get_scene_entities(request: Request):
    return await handle_get_scene_entities(request)


@router.post("/neo4j_query")
async def neo4j_query(request: Request):
    return await handle_neo4j_query(await request.json())


@router.get("/get_koqathemeWithpermission")
async def get_koqatheme_with_permission(userID: str):
    return await handle_get_koqatheme_with_permission(userID)


@router.get("/get_koqascenariosWithpermission")
async def get_koqascenarios_with_permission(selectedMainTopic: str, userID: str):
    return await handle_get_koqascenarios_with_permission(userID, selectedMainTopic)
