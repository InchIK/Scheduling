from pydantic import BaseModel
from datetime import date
from typing import List, Optional

class EmployeeBase(BaseModel):
    name: str
    email: str

class EmployeeCreate(EmployeeBase):
    pass

class Employee(EmployeeBase):
    id: int
    
    class Config:
        orm_mode = True

class HolidayBase(BaseModel):
    date: date
    employee_id: Optional[int] = None

class HolidayCreate(HolidayBase):
    is_weekend: bool = False

class Holiday(HolidayBase):
    id: int
    
    class Config:
        orm_mode = True 

class HolidayAssignment(BaseModel):
    date: date
    employee_id: Optional[int] = None 