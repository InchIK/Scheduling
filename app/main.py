from fastapi import FastAPI, Request, Depends, HTTPException, File, UploadFile
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from . import models, schemas
from .database import SessionLocal, engine
from datetime import datetime, date, timedelta
import calendar
import csv
import io
import random
import colorsys

# 確保資料庫表格被正確創建
models.Base.metadata.create_all(bind=engine)

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def generate_distinct_color(existing_colors):
    """生成一個與現有顏色差異較大的新顏色"""
    def color_distance(c1, c2):
        """計算兩個顏色的差異度"""
        # 將十六進制顏色轉換為 HSV
        def hex_to_hsv(hex_color):
            # 移除 # 符號
            hex_color = hex_color.lstrip('#')
            # 轉換為 RGB
            rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
            # 轉換為 0-1 範圍
            rgb = tuple(x/255.0 for x in rgb)
            # 轉換為 HSV
            return colorsys.rgb_to_hsv(*rgb)
        
        hsv1 = hex_to_hsv(c1)
        hsv2 = hex_to_hsv(c2)
        
        # 計算 HSV 空間中的差異
        h_diff = min(abs(hsv1[0] - hsv2[0]), 1 - abs(hsv1[0] - hsv2[0]))
        s_diff = abs(hsv1[1] - hsv2[1])
        v_diff = abs(hsv1[2] - hsv2[2])
        
        return h_diff * 0.5 + s_diff * 0.25 + v_diff * 0.25

    def generate_color():
        # 生成高飽和度和中等亮度顏色
        h = random.random()
        s = random.uniform(0.7, 1.0)  # 高飽和度
        v = random.uniform(0.6, 0.9)  # 中等亮度
        
        # 轉換為 RGB
        rgb = colorsys.hsv_to_rgb(h, s, v)
        # 轉換為十六進制
        return '#{:02x}{:02x}{:02x}'.format(
            int(rgb[0] * 255),
            int(rgb[1] * 255),
            int(rgb[2] * 255)
        )

    # 如果沒有現有顏色，直接生成一個
    if not existing_colors:
        return generate_color()

    # 生成多個候選顏色，選擇差異最大的
    candidates = [generate_color() for _ in range(50)]
    best_color = max(candidates, key=lambda c: min(
        color_distance(c, ec) for ec in existing_colors
    ))
    
    return best_color

@app.get("/")
async def schedule_page(request: Request, db: Session = Depends(get_db)):
    today = date.today()
    cal = calendar.monthcalendar(today.year, today.month)
    holidays = db.query(models.Holiday).all()
    employees = db.query(models.Employee).all()
    
    return templates.TemplateResponse(
        "schedule.html",
        {
            "request": request,
            "calendar": cal,
            "holidays": holidays,
            "employees": employees
        }
    )

@app.get("/admin")
async def admin_page(request: Request, db: Session = Depends(get_db)):
    current_date = datetime.now()
    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "current_year": current_date.year,
            "current_month": current_date.month
        }
    )

@app.post("/api/employees")
async def create_employee(employee: schemas.EmployeeCreate, db: Session = Depends(get_db)):
    # 檢查是否已存在相同的 email 或 name
    existing_employee = db.query(models.Employee).filter(
        (models.Employee.email == employee.email) | 
        (models.Employee.name == employee.name)
    ).first()
    
    if existing_employee:
        if existing_employee.email == employee.email:
            raise HTTPException(status_code=400, detail="此 Email 已被使用")
        else:
            raise HTTPException(status_code=400, detail="此姓名已被使用")
    
    # 獲取現有的顏色
    existing_colors = [emp.color for emp in db.query(models.Employee).all()]
    
    # 生成新的顏色
    new_color = generate_distinct_color(existing_colors)
    
    # 創建新員工
    db_employee = models.Employee(
        name=employee.name,
        email=employee.email,
        color=new_color  # 使用生成的顏色
    )
    
    try:
        db.add(db_employee)
        db.commit()
        db.refresh(db_employee)
        return db_employee
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/employees/{employee_id}")
async def delete_employee(employee_id: int, db: Session = Depends(get_db)):
    employee = db.query(models.Employee).filter(models.Employee.id == employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    db.delete(employee)
    db.commit()
    return {"status": "success"}

@app.post("/api/holidays")
async def create_or_toggle_holiday(holiday: schemas.HolidayCreate, db: Session = Depends(get_db)):
    # 將日期字串轉換為 date 物件
    if isinstance(holiday.date, str):
        holiday_date = datetime.strptime(holiday.date, '%Y-%m-%d').date()
    else:
        holiday_date = holiday.date

    # 查找是否已存在記錄
    existing_holiday = db.query(models.Holiday).filter(
        models.Holiday.date == holiday_date
    ).first()

    # 如果已存在記錄，則刪除它
    if existing_holiday:
        db.delete(existing_holiday)
        db.commit()
        return {"status": "removed", "date": holiday_date.strftime("%Y-%m-%d")}

    # 如果不存在記錄，則新增一個
    db_holiday = models.Holiday(
        date=holiday_date,
        employee_id=None
    )
    db.add(db_holiday)
    db.commit()
    db.refresh(db_holiday)
    return {"status": "added", "date": holiday_date.strftime("%Y-%m-%d")}

@app.get("/api/employees")
async def get_employees(db: Session = Depends(get_db)):
    employees = db.query(models.Employee).all()
    return [
        {
            "id": emp.id,
            "name": emp.name,
            "email": emp.email,
            "color": emp.color
        }
        for emp in employees
    ]

@app.get("/api/holidays/{year}")
async def get_holidays_by_year(year: int, db: Session = Depends(get_db)):
    start_date = date(year, 1, 1)
    end_date = date(year, 12, 31)
    
    # 獲取資料庫中的假日
    db_holidays = db.query(models.Holiday).filter(
        models.Holiday.date >= start_date,
        models.Holiday.date <= end_date
    ).all()
    
    # 轉換為前端需要的格式
    all_holidays = [
        {
            "id": holiday.id,
            "date": holiday.date.strftime("%Y-%m-%d"),
            "employee_id": holiday.employee_id
        }
        for holiday in db_holidays
    ]
    
    return all_holidays

@app.get("/schedule/assign")
async def schedule_assign_page(request: Request, db: Session = Depends(get_db)):
    holidays = db.query(models.Holiday).order_by(models.Holiday.date).all()
    employees = db.query(models.Employee).all()
    return templates.TemplateResponse(
        "schedule_assign.html",
        {
            "request": request,
            "holidays": holidays,
            "employees": employees
        }
    )

@app.post("/api/holidays/assign")
async def assign_holiday(assignment: schemas.HolidayAssignment, db: Session = Depends(get_db)):
    holiday = db.query(models.Holiday).filter(
        models.Holiday.date == assignment.date
    ).first()
    
    if holiday:
        holiday.employee_id = assignment.employee_id
        db.commit()
        return {"status": "success"}
    
    return {"status": "holiday not found"}

@app.delete("/api/holidays/clear/{year}")
async def clear_holidays(year: int, db: Session = Depends(get_db)):
    try:
        # 只刪除指定年份的假日記錄
        start_date = date(year, 1, 1)
        end_date = date(year, 12, 31)
        
        deleted_count = db.query(models.Holiday).filter(
            models.Holiday.date >= start_date,
            models.Holiday.date <= end_date
        ).delete()
        
        db.commit()
        return {
            "status": "success", 
            "message": f"{year}年的假日記錄已清除，共刪除 {deleted_count} 筆記錄"
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/holidays/import")
async def import_holidays(file: UploadFile = File(...), year: int = None, db: Session = Depends(get_db)):
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="只接受 CSV 檔案")
    
    try:
        content = await file.read()
        csv_file = io.StringIO(content.decode('utf-8-sig'))
        csv_reader = csv.DictReader(csv_file)
        
        imported_count = 0
        
        # 先清除該年份的所有假日
        if year:
            start_date = date(year, 1, 1)
            end_date = date(year, 12, 31)
            db.query(models.Holiday).filter(
                models.Holiday.date >= start_date,
                models.Holiday.date <= end_date
            ).delete()
        
        for row in csv_reader:
            # 跳過空行或沒有日期的行
            if not row.get('Start Date'):
                continue
            
            try:
                # 解析日期
                date_str = row['Start Date'].strip()
                holiday_date = datetime.strptime(date_str, '%Y/%m/%d').date()
                
                # 檢查年份是否匹配
                if year and holiday_date.year != year:
                    continue
                
                # 檢查是否為全天事件且 Subject 不為空
                if row.get('All Day Event', '').upper() == 'TRUE' and row.get('Subject'):
                    db_holiday = models.Holiday(
                        date=holiday_date,
                        employee_id=None
                    )
                    db.add(db_holiday)
                    imported_count += 1
            
            except ValueError as e:
                print(f"跳過無效日期: {date_str}")
                continue
        
        db.commit()
        return {
            "status": "success",
            "message": f"假日資料已匯入，新增了 {imported_count} 筆記錄"
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/holidays/auto-assign")
async def auto_assign_holidays(year: int, db: Session = Depends(get_db)):
    try:
        start_date = date(year, 1, 1)
        end_date = date(year, 12, 31)
        
        holidays = db.query(models.Holiday).filter(
            models.Holiday.date >= start_date,
            models.Holiday.date <= end_date
        ).order_by(models.Holiday.date).all()
        
        employees = db.query(models.Employee).all()
        
        if not employees:
            raise HTTPException(status_code=400, detail="沒有可用的員工")
        
        if not holidays:
            raise HTTPException(status_code=400, detail="沒有需要分配的假日")
        
        # 隨機打亂員工順序
        random_order_employees = list(employees)
        random.shuffle(random_order_employees)
        
        # 記錄打亂後的順序
        employee_order = " → ".join([emp.name for emp in random_order_employees])
        
        # 初始化每個員工的假日計數
        employee_counts = {emp.id: 0 for emp in employees}
        
        # 找出連續假日組
        holiday_groups = []
        single_holidays = []
        current_group = []
        
        for i in range(len(holidays)):
            if not current_group:
                current_group.append(holidays[i])
            else:
                if (holidays[i].date - current_group[-1].date).days == 1:
                    current_group.append(holidays[i])
                else:
                    # 處理當前組
                    if len(current_group) >= 2:
                        # 如果是3天或以上，分成兩天一組，剩餘的加入單日列表
                        while len(current_group) >= 2:
                            holiday_groups.append([current_group[0], current_group[1]])
                            current_group = current_group[2:]
                        # 處理剩餘的單日
                        single_holidays.extend(current_group)
                    else:
                        single_holidays.extend(current_group)
                    current_group = [holidays[i]]
        
        # 處理最後一組
        if current_group:
            if len(current_group) >= 2:
                while len(current_group) >= 2:
                    holiday_groups.append([current_group[0], current_group[1]])
                    current_group = current_group[2:]
                single_holidays.extend(current_group)
            else:
                single_holidays.extend(current_group)
        
        # 當前分配到的員工索引
        current_employee_index = 0
        
        # 分配連續假日組（兩天一組）
        for group in holiday_groups:
            employee = random_order_employees[current_employee_index]
            
            # 分配整組假日
            for holiday in group:
                holiday.employee_id = employee.id
                employee_counts[employee.id] += 1
            
            # 移到下一個員工
            current_employee_index = (current_employee_index + 1) % len(random_order_employees)
        
        # 分配單日假日
        for holiday in single_holidays:
            # 隨機選擇一個員工，但不影響輪替順序
            random_employee = random.choice(employees)
            holiday.employee_id = random_employee.id
            employee_counts[random_employee.id] += 1
        
        # 保存分配結果
        db.commit()
        
        # 計算權重（修改權重計算邏輯）
        sorted_employees = sorted(
            random_order_employees,
            key=lambda emp: employee_counts[emp.id],
            reverse=True
        )
        max_days = employee_counts[sorted_employees[0].id]
        min_days = employee_counts[sorted_employees[-1].id]
        day_range = max_days - min_days
        
        # 使用更平滑的權重計算
        weights = {}
        for emp in sorted_employees:
            days_diff = max_days - employee_counts[emp.id]
            if day_range == 0:
                weights[emp.id] = 0
            else:
                # 將權重範圍限制在 0-3 之間
                weights[emp.id] = round((days_diff / day_range) * 3)
        
        # 生成分配報告
        assignment_report = {
            "order": employee_order,
            "results": [
                {
                    "id": emp.id,
                    "name": emp.name,
                    "color": emp.color,
                    "total_days": employee_counts[emp.id],
                    "continuous_days": sum(2 for g in holiday_groups if g[0].employee_id == emp.id),
                    "single_days": sum(1 for h in single_holidays if h.employee_id == emp.id),
                    "weight": weights[emp.id]
                }
                for emp in sorted_employees
            ]
        }
        
        return {
            "status": "success",
            "data": assignment_report
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/holidays/assignment-stats")
async def get_assignment_stats(year: int, db: Session = Depends(get_db)):
    # 獲取該年度的所有假日和分配情況
    start_date = date(year, 1, 1)
    end_date = date(year, 12, 31)
    
    holidays = db.query(models.Holiday).filter(
        models.Holiday.date >= start_date,
        models.Holiday.date <= end_date
    ).order_by(models.Holiday.date).all()
    
    employees = db.query(models.Employee).all()
    
    # 計算每個員工的假日統計
    employee_counts = {emp.id: 0 for emp in employees}
    continuous_days = {emp.id: 0 for emp in employees}
    single_days = {emp.id: 0 for emp in employees}
    
    # 計算連續假日和單日假日
    current_group = []
    for holiday in holidays:
        if holiday.employee_id:
            employee_counts[holiday.employee_id] += 1
            
            if not current_group or (holiday.date - current_group[-1].date).days == 1:
                current_group.append(holiday)
            else:
                # 處理前一組
                if len(current_group) >= 2:
                    emp_id = current_group[0].employee_id
                    continuous_days[emp_id] += len(current_group)
                else:
                    for h in current_group:
                        single_days[h.employee_id] += 1
                current_group = [holiday]
    
    # 處理最後一組
    if current_group:
        if len(current_group) >= 2:
            emp_id = current_group[0].employee_id
            continuous_days[emp_id] += len(current_group)
        else:
            for h in current_group:
                single_days[h.employee_id] += 1
    
    # 計算權重
    sorted_employees = sorted(
        employees,
        key=lambda emp: employee_counts[emp.id],
        reverse=True
    )
    max_days = max(employee_counts.values()) if employee_counts else 0
    weights = {
        emp.id: round((max_days - employee_counts[emp.id]) * 0.5)
        for emp in employees
    }
    
    return {
        "order": " → ".join([emp.name for emp in sorted_employees]),
        "results": [
            {
                "id": emp.id,
                "name": emp.name,
                "color": emp.color,
                "total_days": employee_counts[emp.id],
                "continuous_days": continuous_days[emp.id],
                "single_days": single_days[emp.id],
                "weight": weights[emp.id]
            }
            for emp in sorted_employees
        ]
    }