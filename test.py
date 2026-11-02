from typing import TypedDict


class Movie(TypedDict):
    name: str
    year: int

    def method(self): pass

my_movie = Movie({"name": "Foo", "year": 1984})
my_movie.method()