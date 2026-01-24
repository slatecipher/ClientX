from pydantic import BaseModel, Field, HttpUrl, TypeAdapter


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

    Attributes:
        id: Numeric identifier for the company.
        name: Company name.
        address: Street address.
        zip: Postal code, stored as a string for hyphenated zips.
        country: Country name.
        employeeCount: Number of employees.
        industry: Industry category.
        marketCap: Market capitalization value.
        domain: Company domain name.
        logo: URL to the company logo image.
        ceoName: CEO full name.
    """

    id: int
    name: str
    address: str
    zip: str = Field(..., description="Postal code (string because of hyphenated zips)")
    country: str
    employeeCount: int = Field(..., ge=0)
    industry: str
    marketCap: int = Field(..., ge=0)
    domain: str
    logo: HttpUrl
    ceoName: str


Companies = TypeAdapter(list[Company])
