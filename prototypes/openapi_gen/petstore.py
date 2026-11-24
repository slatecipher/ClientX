"""Generated from Swagger Petstore - OpenAPI 3.0 1.0.30-SNAPSHOT.

Don't edit: regenerate with prototypes/openapi_gen/generate.py.
"""

from collections.abc import Generator
from datetime import datetime
from typing import Annotated, Literal

import httpx2
from clientx import Body, ClientX, Header, Json, Query, Resource, method
from pydantic import BaseModel, ConfigDict, Field


class Order(BaseModel):
    """The ``Order`` schema."""

    model_config = ConfigDict(validate_by_name=True, validate_by_alias=True)

    id: int | None = None
    pet_id: int | None = Field(None, alias="petId")
    quantity: int | None = None
    ship_date: datetime | None = Field(None, alias="shipDate")
    status: Literal["placed", "approved", "delivered"] | None = Field(None, description="Order Status")
    complete: bool | None = None


class Category(BaseModel):
    """The ``Category`` schema."""

    id: int | None = None
    name: str | None = None


class User(BaseModel):
    """The ``User`` schema."""

    model_config = ConfigDict(validate_by_name=True, validate_by_alias=True)

    id: int | None = None
    username: str | None = None
    first_name: str | None = Field(None, alias="firstName")
    last_name: str | None = Field(None, alias="lastName")
    email: str | None = None
    password: str | None = None
    phone: str | None = None
    user_status: int | None = Field(None, alias="userStatus", description="User Status")


class Tag(BaseModel):
    """The ``Tag`` schema."""

    id: int | None = None
    name: str | None = None


class Pet(BaseModel):
    """The ``Pet`` schema."""

    model_config = ConfigDict(validate_by_name=True, validate_by_alias=True)

    id: int | None = None
    name: str
    category: Category | None = None
    photo_urls: list[str] = Field(alias="photoUrls")
    tags: list[Tag] | None = None
    status: Literal["available", "pending", "sold"] | None = Field(None, description="pet status in the store")


class ApiResponse(BaseModel):
    """The ``ApiResponse`` schema."""

    code: int | None = None
    type: str | None = None
    message: str | None = None


class PetResource(Resource, prefix="/pet", tags=["pet"]):
    """Everything about your Pets."""

    @method.put()
    def update_pet(self, pet: Annotated[Pet, Json(description="Update an existent pet in the store")]) -> Pet:
        """Update an existing pet.

        Update an existing pet by Id.
        """
        ...

    @method.post()
    def add_pet(self, pet: Annotated[Pet, Json(description="Create a new pet in the store")]) -> Pet:
        """Add a new pet to the store."""
        ...

    @method.get("/findByStatus")
    def find_pets_by_status(
        self,
        status: Annotated[
            Literal["available", "pending", "sold"],
            Query(description="Status values that need to be considered for filter"),
        ] = "available",
    ) -> list[Pet]:
        """Finds Pets by status.

        Multiple status values can be provided with comma separated strings.
        """
        ...

    @method.get("/findByTags")
    def find_pets_by_tags(self, tags: Annotated[list[str], Query(description="Tags to filter by")]) -> list[Pet]:
        """Finds Pets by tags.

        Multiple tags can be provided with comma separated strings. Use tag1,
        tag2, tag3 for testing.
        """
        ...

    @method.get("/{pet_id}")
    def get_pet_by_id(self, pet_id: int) -> Pet:
        """Find pet by ID.

        Returns a single pet.
        """
        ...

    @method.post("/{pet_id}")
    def update_pet_with_form(
        self,
        pet_id: int,
        name: Annotated[str | None, Query(description="Name of pet that needs to be updated")] = None,
        status: Annotated[str | None, Query(description="Status of pet that needs to be updated")] = None,
    ) -> Pet:
        """Updates a pet in the store with form data.

        Updates a pet resource based on the form data.
        """
        ...

    @method.delete("/{pet_id}")
    def delete_pet(self, pet_id: int, api_key: Annotated[str | None, Header(alias="api_key")] = None) -> None:
        """Deletes a pet.

        Delete a pet.
        """
        ...

    @method.post("/{pet_id}/uploadImage")
    def upload_file(
        self,
        pet_id: int,
        additional_metadata: Annotated[
            str | None, Query(alias="additionalMetadata", description="Additional Metadata")
        ] = None,
        body: Annotated[bytes | None, Body()] = None,
    ) -> ApiResponse:
        """Uploads an image.

        Upload image of the pet.
        """
        ...


class StoreResource(Resource, prefix="/store", tags=["store"]):
    """Access to Petstore orders."""

    @method.get("/inventory")
    def get_inventory(self) -> dict[str, int]:
        """Returns pet inventories by status.

        Returns a map of status codes to quantities.
        """
        ...

    @method.post("/order")
    def place_order(self, order: Annotated[Order | None, Json()] = None) -> Order:
        """Place an order for a pet.

        Place a new order in the store.
        """
        ...

    @method.get("/order/{order_id}")
    def get_order_by_id(self, order_id: int) -> Order:
        """Find purchase order by ID.

        For valid response try integer IDs with value <= 5 or > 10. Other values
        will generate exceptions.
        """
        ...

    @method.delete("/order/{order_id}")
    def delete_order(self, order_id: int) -> None:
        """Delete purchase order by identifier.

        For valid response try integer IDs with value < 1000. Anything above
        1000 or non-integers will generate API errors.
        """
        ...


class UserResource(Resource, prefix="/user", tags=["user"]):
    """Operations about user."""

    @method.post()
    def create_user(self, user: Annotated[User | None, Json(description="Created user object")] = None) -> User:
        """Create user.

        This can only be done by the logged in user.
        """
        ...

    @method.post("/createWithList")
    def create_users_with_list_input(self, users: Annotated[list[User] | None, Json()] = None) -> User:
        """Creates list of users with given input array."""
        ...

    # TODO(openapi): response headers (X-Rate-Limit, X-Expires-After) not typed:
    #   return Response to read them
    # TODO(openapi): JSON string response typed -> str: decoded as raw text, not
    #   JSON
    @method.get("/login")
    def login_user(
        self,
        username: Annotated[str | None, Query(description="The user name for login")] = None,
        password: Annotated[str | None, Query(description="The password for login in clear text")] = None,
    ) -> str:
        """Logs user into the system.

        Log into the system.
        """
        ...

    @method.get("/logout")
    def logout_user(self) -> None:
        """Logs out current logged in user session.

        Log user out of the system.
        """
        ...

    @method.get("/{username}")
    def get_user_by_name(self, username: str) -> User:
        """Get user by user name.

        Get user detail based on username.
        """
        ...

    @method.put("/{username}")
    def update_user(
        self,
        username: str,
        user: Annotated[User | None, Json(description="Update an existent user in the store")] = None,
    ) -> None:
        """Update user resource.

        This can only be done by the logged in user.
        """
        ...

    @method.delete("/{username}")
    def delete_user(self, username: str) -> None:
        """Delete user resource.

        This can only be done by the logged in user.
        """
        ...


class PetstoreClient(ClientX, base_url="https://petstore3.swagger.io/api/v3"):
    """Swagger Petstore - OpenAPI 3.0."""

    pet = PetResource()
    store = StoreResource()
    user = UserResource()


class ApiKeyAuth(httpx2.Auth):
    """Send the ``api_key`` API key in the headers."""

    def __init__(self, key: str) -> None:
        self.key = key

    def auth_flow(self, request: httpx2.Request) -> Generator[httpx2.Request, httpx2.Response]:
        """Add the key to the request."""
        request.headers["api_key"] = self.key
        yield request
