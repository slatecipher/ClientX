from pydantic import BaseModel, ConfigDict, Field, HttpUrl, TypeAdapter


class User(BaseModel):
    """User profile returned by the Beeceptor sample users API.

    Attributes:
        id: Numeric identifier for the user.
        name: Full name.
        company: Employer or organization name.
        username: Username or handle.
        email: Email address.
        address: Street address.
        zip: Postal code.
        state: State or region.
        country: Country name.
        phone: Phone number.
        photo: URL to the user's profile photo.
    """

    id: int
    name: str
    company: str
    username: str
    email: str
    address: str
    zip: str
    state: str
    country: str
    phone: str
    photo: HttpUrl


Users = TypeAdapter(list[User])


class Company(BaseModel):
    """Company profile returned by the Beeceptor sample companies API.

    Field names follow Python ``snake_case`` conventions, while aliases
    preserve the original camelCase field names used by the API.

    Attributes:
        id: Numeric identifier for the company.
        name: Company name.
        address: Street address.
        zip: Postal code, stored as a string for hyphenated ZIP codes.
        country: Country name.
        employee_count: Number of employees.
        industry: Industry category.
        market_cap: Market capitalization value.
        domain: Company domain name.
        logo: URL to the company logo image.
        ceo_name: CEO full name.
    """

    model_config = ConfigDict(validate_by_name=True)

    id: int
    name: str
    address: str
    zip: str = Field(description="Postal code (string because of hyphenated ZIP codes)")
    country: str
    employee_count: int = Field(alias="employeeCount", ge=0)
    industry: str
    market_cap: int = Field(alias="marketCap", ge=0)
    domain: str
    logo: HttpUrl
    ceo_name: str = Field(alias="ceoName")


Companies = TypeAdapter(list[Company])
