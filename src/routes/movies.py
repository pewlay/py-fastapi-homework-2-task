from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    Body,
    Path,
    Response,
)
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy import desc

from database.models import CountryModel, GenreModel, ActorModel, LanguageModel
from database import get_db, MovieModel
from schemas.movies import (
    MovieListResponseSchema,
    MovieDetailResponseSchema,
    MovieSummarySchema,
    MovieCreateSchema,
    MovieUpdate,
)


router = APIRouter()


@router.get(
    "/movies/",
    response_model=MovieListResponseSchema,
    summary="Get paginated list of movies",
)
async def list_movies(
    request: Request,
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(10, ge=1, le=20, description="Movies per page"),
    db: AsyncSession = Depends(get_db),
):
    total_items = (
        await db.execute(select(func.count()).select_from(MovieModel))
    ).scalar()

    if total_items == 0:
        raise HTTPException(status_code=404, detail="No movies found.")

    total_pages = (total_items + per_page - 1) // per_page

    if page > total_pages and total_items > 0:
        raise HTTPException(status_code=404, detail="No movies found.")

    offset = (page - 1) * per_page

    result = await db.execute(
        select(MovieModel)
        .options(
            joinedload(MovieModel.country),
            joinedload(MovieModel.genres),
            joinedload(MovieModel.actors),
            joinedload(MovieModel.languages),
        )
        .order_by(desc(MovieModel.id))
        .offset(offset)
        .limit(per_page)
    )

    movies = result.unique().scalars().all()
    base_path = request.url.path
    prefix = "/api/v1"
    if base_path.startswith(prefix):
        base_path = base_path[len(prefix) :]

    def params(p: int) -> str:
        return f"?page={p}&per_page={per_page}"

    prev_page = f"{base_path}{params(page - 1)}" if page > 1 else None
    next_page = (
        f"{base_path}{params(page + 1)}" if page < total_pages else None
    )

    return {
        "movies": [
            MovieSummarySchema.model_validate(movie) for movie in movies
        ],
        "prev_page": prev_page,
        "next_page": next_page,
        "total_pages": total_pages,
        "total_items": total_items,
    }


@router.get(
    "/movies/{movie_id}/",
    response_model=MovieDetailResponseSchema,
    summary="Get details of a movie by ID",
)
async def get_movie_details(movie_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(MovieModel)
        .options(
            joinedload(MovieModel.country),
            joinedload(MovieModel.genres),
            joinedload(MovieModel.actors),
            joinedload(MovieModel.languages),
        )
        .filter(MovieModel.id == movie_id)
    )

    movie = result.unique().scalar_one_or_none()

    if not movie:
        raise HTTPException(
            status_code=404, detail="Movie with the given ID was not found."
        )

    return MovieDetailResponseSchema.model_validate(movie)


async def get_or_create_country(db: AsyncSession, country_code: str):
    result = await db.execute(
        select(CountryModel).filter(CountryModel.code == country_code)
    )
    country = result.scalar_one_or_none()
    if not country:
        country = CountryModel(code=country_code)
        db.add(country)
        await db.commit()
        await db.refresh(country)
    return country


async def get_or_create_genres(db: AsyncSession, genre_names: list[str]):
    genres = []
    for name in genre_names:
        result = await db.execute(
            select(GenreModel).filter(GenreModel.name == name)
        )
        genre = result.scalar_one_or_none()
        if not genre:
            genre = GenreModel(name=name)
            db.add(genre)
            await db.commit()
            await db.refresh(genre)
        genres.append(genre)
    return genres


async def get_or_create_actors(db: AsyncSession, actor_names: list[str]):
    actors = []
    for name in actor_names:
        result = await db.execute(
            select(ActorModel).filter(ActorModel.name == name)
        )
        actor = result.scalar_one_or_none()
        if not actor:
            actor = ActorModel(name=name)
            db.add(actor)
            await db.commit()
            await db.refresh(actor)
        actors.append(actor)
    return actors


async def get_or_create_languages(db: AsyncSession, language_names: list[str]):
    languages = []
    for name in language_names:
        result = await db.execute(
            select(LanguageModel).filter(LanguageModel.name == name)
        )
        language = result.scalar_one_or_none()
        if not language:
            language = LanguageModel(name=name)
            db.add(language)
            await db.commit()
            await db.refresh(language)
        languages.append(language)
    return languages


async def get_or_create_movie(
    db: AsyncSession, movie_data: MovieCreateSchema
) -> MovieModel:
    result = await db.execute(
        select(MovieModel).filter(
            and_(
                MovieModel.name == movie_data.name,
                MovieModel.date == movie_data.date,
            )
        )
    )
    existing_movie = result.scalar_one_or_none()

    if existing_movie:
        raise HTTPException(
            status_code=409,
            detail=f"A movie with the name '{movie_data.name}' and release date '{movie_data.date}' already exists.",
        )

    country = await get_or_create_country(db, movie_data.country)
    genres = await get_or_create_genres(db, movie_data.genres)
    actors = await get_or_create_actors(db, movie_data.actors)
    languages = await get_or_create_languages(db, movie_data.languages)

    new_movie = MovieModel(
        name=movie_data.name,
        date=movie_data.date,
        score=movie_data.score,
        overview=movie_data.overview,
        status=movie_data.status,
        budget=movie_data.budget,
        revenue=movie_data.revenue,
        country=country,
        genres=genres,
        actors=actors,
        languages=languages,
    )
    db.add(new_movie)
    await db.commit()
    await db.refresh(new_movie)
    return new_movie


@router.post(
    "/movies/", status_code=201, response_model=MovieDetailResponseSchema
)
async def create_movie(
    movie_data: MovieCreateSchema, db: AsyncSession = Depends(get_db)
):
    new_movie = await get_or_create_movie(db, movie_data)

    result = await db.execute(
        select(MovieModel)
        .options(
            selectinload(MovieModel.country),
            selectinload(MovieModel.genres),
            selectinload(MovieModel.actors),
            selectinload(MovieModel.languages),
        )
        .filter(MovieModel.id == new_movie.id)
    )
    movie_with_rels = result.scalar_one()

    return movie_with_rels


@router.delete(
    "/movies/{movie_id}/",
    status_code=204,
    summary="Delete a movie by ID",
)
async def delete_movie(movie_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(MovieModel).filter(MovieModel.id == movie_id)
    )
    movie = result.scalar_one_or_none()
    if not movie:
        raise HTTPException(
            status_code=404, detail="Movie with the given ID was not found."
        )

    await db.delete(movie)
    await db.commit()
    return Response(status_code=204)


@router.put(
    "/movies/{movie_id}/",
    response_model=MovieDetailResponseSchema,
    summary="Update a movie by ID",
)
async def update_movie(
    movie_id: int = Path(..., ge=1),
    movie_data: MovieCreateSchema = Body(...),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MovieModel).filter(MovieModel.id == movie_id)
    )
    movie = result.scalar_one_or_none()
    if not movie:
        raise HTTPException(
            status_code=404, detail="Movie with the given ID was not found."
        )

    movie.name = movie_data.name
    movie.date = movie_data.date
    movie.score = movie_data.score
    movie.overview = movie_data.overview
    movie.status = movie_data.status
    movie.budget = movie_data.budget
    movie.revenue = movie_data.revenue

    movie.country = await get_or_create_country(db, movie_data.country)
    movie.genres = await get_or_create_genres(db, movie_data.genres)
    movie.actors = await get_or_create_actors(db, movie_data.actors)
    movie.languages = await get_or_create_languages(db, movie_data.languages)

    db.add(movie)
    await db.commit()
    await db.refresh(movie)

    return movie


async def get_movie_by_id(movie_id: int, db: AsyncSession):
    stmt = select(MovieModel).where(MovieModel.id == movie_id)
    result = await db.execute(stmt)
    movie = result.scalar_one_or_none()
    return movie


@router.patch("/movies/{movie_id}/")
async def update_movie_details(
    movie_id: int,
    movie_update: MovieUpdate,
    db: AsyncSession = Depends(get_db),
):
    movie = await get_movie_by_id(movie_id, db)
    if not movie:
        raise HTTPException(
            status_code=404, detail="Movie with the given ID was not found."
        )

    if movie_update.name is not None:
        movie.name = movie_update.name
    if movie_update.score is not None:
        movie.score = movie_update.score

    await db.commit()
    await db.refresh(movie)

    return {"detail": "Movie updated successfully."}
