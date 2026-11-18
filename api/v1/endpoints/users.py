from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_session_store, registration_access, require_roles
from models.enums import UserRole
from models.user import User
from schemas.user import UserCreate, UserInfo, UserUpdate
from services import user as user_service

from core.db import get_session
from core.exceptions import CustomError, CustomException
from core.sessions import RedisSessionStore


def prevent_caching(response: Response) -> None:
    """Запрещает кеширование ответов с персональными данными."""
    response.headers['Cache-Control'] = 'no-store'


router = APIRouter(prefix='/users', dependencies=[Depends(prevent_caching)])
Session = Annotated[AsyncSession, Depends(get_session)]
Store = Annotated[RedisSessionStore, Depends(get_session_store)]
CurrentUser = Annotated[User, Depends(require_roles(UserRole.USER, UserRole.MANAGER, UserRole.ADMIN))]
StaffUser = Annotated[User, Depends(require_roles(UserRole.MANAGER, UserRole.ADMIN))]
AdminUser = Annotated[User, Depends(require_roles(UserRole.ADMIN))]
UserId = Annotated[int, Path(gt=0, lt=2**31)]
ERRORS = {
    code: {'model': CustomError}
    for code in (
        status.HTTP_400_BAD_REQUEST,
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
        status.HTTP_404_NOT_FOUND,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        status.HTTP_503_SERVICE_UNAVAILABLE,
    )
}


@router.post(
    '',
    response_model=UserInfo,
    status_code=status.HTTP_201_CREATED,
    operation_id='create_user_users_post',
    openapi_extra={'security': [{}]},
    summary='Регистрация нового пользователя',
    responses=ERRORS,
)
async def register(
    data: UserCreate,
    session: Session,
    actor: Annotated[User | None, Depends(registration_access)],
) -> UserInfo:
    """Регистрирует активного USER; роль и статус не принимаются от клиента."""
    return await user_service.create_user(session, data)


@router.get(
    '',
    response_model=list[UserInfo],
    operation_id='get_all_user_users_get',
    summary='Получение списка пользователей',
    responses=ERRORS,
)
async def get_users(session: Session, actor: StaffUser) -> list[User]:
    """Разрешает чтение списка администратору и менеджеру."""
    return await user_service.list_users(session)


@router.get(
    '/me',
    response_model=UserInfo,
    operation_id='get_me_users_me_get',
    summary='Получение информации о текущем пользователе',
    responses={
        status.HTTP_401_UNAUTHORIZED: {'model': CustomError, 'description': 'Требуется авторизация'},
        status.HTTP_403_FORBIDDEN: {'model': CustomError, 'description': 'Недостаточно прав'},
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            'model': CustomError,
            'description': 'Авторизация временно недоступна',
        },
    },
)
async def get_me(
    response: Response,
    user: CurrentUser,
) -> User:
    """Возвращает собственный профиль активного USER, MANAGER или ADMIN без хеша пароля."""
    response.headers['Cache-Control'] = 'no-store'
    return user


@router.patch(
    '/me',
    response_model=UserInfo,
    operation_id='path_me_users_me_patch',
    summary='Обновление информации о текущем пользователе',
    responses=ERRORS,
)
async def update_me(
    data: UserUpdate,
    request: Request,
    session: Session,
    store: Store,
    user: CurrentUser,
) -> UserInfo:
    """Запрещает изменение роли/активности через профиль; новый пароль завершает все сессии."""
    if data.model_fields_set & {'role', 'is_active'}:
        raise CustomException(
            code=status.HTTP_403_FORBIDDEN,
            message='Недостаточно прав',
            status_code=status.HTTP_403_FORBIDDEN,
        )
    result, revoked = await user_service.update_user(session, user.id, data, store)
    if revoked:
        request.state.auth_session = None
    return result


@router.get(
    '/{user_id}',
    response_model=UserInfo,
    operation_id='get_user_by_id_users__user_id__get',
    summary='Получение информации о пользователе по его ID',
    responses=ERRORS,
)
async def get_user_by_id(user_id: UserId, session: Session, actor: StaffUser) -> User:
    """Разрешает чтение пользователя администратору и менеджеру."""
    return await user_service.get_user(session, user_id)


@router.patch(
    '/{user_id}',
    response_model=UserInfo,
    operation_id='path_user_by_id_users__user_id__patch',
    summary='Обновление информации о пользователе по его ID',
    responses=ERRORS,
)
async def update_user_by_id(
    user_id: UserId,
    data: UserUpdate,
    request: Request,
    session: Session,
    store: Store,
    actor: AdminUser,
) -> UserInfo:
    """Меняет данные, роль, блокировку; после отзыва своей сессии сохраняет успешный ответ."""
    if data.model_fields_set == {'is_active'} and data.is_active is False:
        result = await user_service.delete_user(session, user_id, store)
        revoked = True
    else:
        result, revoked = await user_service.update_user(session, user_id, data, store)
    if revoked and user_id == actor.id:
        request.state.auth_session = None
    return result
