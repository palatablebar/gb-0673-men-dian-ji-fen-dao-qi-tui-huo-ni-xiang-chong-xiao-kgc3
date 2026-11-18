from fastapi import APIRouter, Request, Body
from app.engine import evaluate
from app.web import render
router=APIRouter()
@router.get('/reminder')
def page(request:Request):
    return render(request,'reminder')
@router.post('/api/reminder')
def calculate(payload:dict=Body(default={})):
    return evaluate(payload,until=6)
