"""Phase 7 LangGraph workflow: search -> budget -> itinerary -> approval."""
from __future__ import annotations
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from app.agents.search import SearchAgent
from app.services.budget_optimizer import BudgetAgent
from app.services.itinerary_optimizer import ItineraryAgent
from app.schemas.request import TripRequest
from app.db.store import PlanStore

class WorkflowState(TypedDict, total=False): request: TripRequest; search: object; budget: object; itinerary: object; retries:int; plan_id:str; version:int; status:str; warnings:list[str]; thread_id:str; owner_id:str
class Orchestrator:
 def __init__(self,search:SearchAgent,budget:BudgetAgent,itinerary:ItineraryAgent,store:PlanStore):
  self.search,self.budget,self.itinerary,self.store=search,budget,itinerary,store
  graph=StateGraph(WorkflowState);graph.add_node("search",self._search);graph.add_node("budget",self._budget);graph.add_node("itinerary",self._itinerary);graph.add_node("approval",self._approval);graph.add_edge(START,"search");graph.add_edge("search","budget");graph.add_edge("budget","itinerary");graph.add_edge("itinerary","approval");graph.add_edge("approval",END);self.graph=graph.compile()
 async def run(self,thread_id:str,request:TripRequest,owner_id:str="anonymous"): return await self.graph.ainvoke({"request":request,"retries":0,"warnings":[],"thread_id":thread_id,"owner_id":owner_id})
 async def _search(self,s): return {"search":await self.search.search(s["request"])}
 def _budget(self,s): return {"budget":self.budget.build(s["request"],s["search"])}
 def _itinerary(self,s): return {"itinerary":self.itinerary.plan(s["request"],s["search"])}
 def _approval(self,s):
  payload={"request":s["request"].model_dump(mode="json"),"search":s["search"].model_dump(mode="json"),"budget":s["budget"].model_dump(mode="json"),"itinerary":s["itinerary"].model_dump(mode="json")};pid,v=self.store.save_plan(s.get("thread_id","default"),payload,s.get("owner_id","anonymous"));return {"plan_id":pid,"version":v,"status":"AWAITING_APPROVAL"}
