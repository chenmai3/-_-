from fastapi import APIRouter, File, Form, Request, UploadFile

from .batch_rule_generation import handle_rule_generation, handle_upload_rule
from .graph_match import handle_neo4j_match, handle_neo4j_match_1, handle_neo4j_query
from .permissions import (
    handle_add_theme_permission,
    handle_delete_permission,
    handle_delete_theme,
    handle_get_koqascenarios,
    handle_get_koqascenarios_with_permission,
    handle_get_koqatheme,
    handle_get_koqatheme_with_permission,
    handle_has_permission_to_add,
)
from .rule_generate_stream import handle_rule_generate
from .rule_repository import handle_new_rule_submit, handle_rule_delete, handle_sql_polling


router = APIRouter(prefix="/rule", tags=["rule_construct.vue"])


@router.post("/uploadRule")
async def upload_rule(
    file: UploadFile = File(...),
    userId: str = Form(None),
    selectedMainTopic: str = Form(None),
    selectedScenario: str = Form(None),
):
    return await handle_upload_rule(file, selectedMainTopic, selectedScenario, userId)


# @router.post("/fileRuleConstruct")
# async def file_rule_construct(
#     file: UploadFile = File(...),
#     userId: str = Form(...),
#     selectedMainTopic: str = Form(...),
#     selectedScenario: str = Form(...),
# ):
#     return await handle_upload_rule(file, selectedMainTopic, selectedScenario, userId)


@router.post("/rule_generation")
async def rule_generation(request: Request):
    return await handle_rule_generation(await request.json())


@router.post("/rule_delete")
async def rule_delete(request: Request):
    return await handle_rule_delete(await request.json())


@router.post("/neo4j_match_1")
async def neo4j_match_1(request: Request):
    return await handle_neo4j_match_1(await request.json())


@router.post("/sql_polling")
async def sql_polling(request: Request):
    return await handle_sql_polling(await request.json())


@router.post("/neo4j_match")
async def neo4j_match(request: Request):
    return await handle_neo4j_match(await request.json())


@router.post("/neo4j_query")
async def neo4j_query(request: Request):
    return await handle_neo4j_query(await request.json())


@router.post("/rule_generate")
async def rule_generate(request: Request):
    return await handle_rule_generate(await request.json())


@router.post("/new_rule_submit")
async def new_rule_submit(request: Request):
    return await handle_new_rule_submit(await request.json())


@router.get("/get_koqathemeWithpermission")
async def get_koqatheme_with_permission(userID: str):
    return await handle_get_koqatheme_with_permission(userID)


@router.get("/get_koqascenariosWithpermission")
async def get_koqascenarios_with_permission(selectedMainTopic: str, userID: str):
    return await handle_get_koqascenarios_with_permission(userID, selectedMainTopic)


@router.get("/get_koqatheme")
async def get_koqatheme():
    return await handle_get_koqatheme()


@router.get("/get_koqascenarios")
async def get_koqascenarios(selectedMainTopic: str):
    return await handle_get_koqascenarios(selectedMainTopic)


@router.post("/has_permissiontoadd")
async def has_permission_to_add(request: Request):
    return await handle_has_permission_to_add(await request.json())


@router.post("/add_theme_permission")
async def add_theme_permission(request: Request):
    return await handle_add_theme_permission(await request.json())


@router.post("/del_permission")
async def delete_permission(request: Request):
    return await handle_delete_permission(await request.json())


@router.post("/del_koqatheme")
async def delete_theme(request: Request):
    return await handle_delete_theme(await request.json())
