"""Resource-workspace form definitions. Bounds validate records, not agronomy."""
from nexus.farm_app.resource_formtypes import f,choice,spec
SPECS={
 'supply':spec('Supply catalogue','Register one item and a fixed stock unit. Keep unlike materials or units as separate items.','Saves catalogue details. Opening stock must be recorded separately as a receipt or adjustment.',[
  f('name','Item name'),choice('unit','Stock unit',['kg','g','litre','ml','bag','piece','metre']),f('minimum','User-selected low-stock marker','quantity',False),f('storage','Storage location or Unknown'),f('notes','Limitations / item description','textarea')]),
 'movement':spec('Supply movements','Record a receipt, issue or counted stock adjustment for one saved supply.','Changes the calculated recorded balance. It does not apply any material to a field or record an expense.',[
  f('supply_id','Supply item','reference',ref='supply'),choice('direction','Movement',['receipt','issue','adjustment']),f('quantity','Quantity in the item unit; signed for adjustment','signed_quantity'),f('occurred_at','Actual movement time','datetime'),f('reference','Receipt / issue reference or Unknown'),f('notes','What happened and limitations','textarea')]),
 'reservation':spec('Supply reservations','Plan a quantity for named work. A reservation is separate from a stock issue.','Active reservations reduce available stock only. Released or fulfilled reservations do not deduct stock; record an issue separately.',[
  f('supply_id','Supply item','reference',ref='supply'),f('quantity','Reserved quantity in the item unit','quantity'),f('purpose','Purpose / planned work'),choice('status','Reservation status',['active','released','fulfilled']),f('due_date','Needed by (Lagos date)','date'),f('notes','Constraints and limitations','textarea')]),
 'equipment':spec('Equipment register','Identify equipment and its user-reported condition.','Saves reported asset details; condition is not an inspection certificate.',[
  f('name','Equipment name'),f('identifier','Tag / serial or Unknown'),choice('condition','Reported condition',['unknown','serviceable','needs_check','out_of_service']),f('owner','Custodian / owner as reported'),f('notes','Condition basis and limitations','textarea')]),
 'maintenance':spec('Maintenance plans','Plan maintenance for registered equipment, then revise when work is actually recorded.','Adds a plan or reported completion. It does not operate equipment or complete workspace tasks.',[
  f('equipment_id','Equipment','reference',ref='equipment'),f('name','Maintenance activity'),f('due_date','Due date (Lagos date)','date'),choice('status','Status',['planned','in_progress','completed','cancelled']),f('performed_at','Actual completion time; required when completed','datetime',False),f('findings','Work performed / remaining uncertainty or planned scope','textarea')]),
 'labor':spec('Labour activity','Record work actually performed and optional agreed cost. Names and amounts are user-entered.','Saves an activity and calculates hours × hourly rate where both are recorded. It does not record payment or create a finance expense.',[
  f('name','Activity'),f('worker','Worker / team as reported'),f('occurred_at','Actual work time','datetime'),f('hours','Total person-hours','quantity'),f('hourly_ngn','Agreed NGN per person-hour; blank if unknown','money',False),f('notes','Work, evidence and limitations','textarea')]),
 'budget':spec('Budget plans','Set a field budget ceiling and period, keeping expected costs separate from actual cash entries.','Stores a plan. Budget lines are estimates or commitments, never automatically actual expenses.',[
  f('name','Budget name'),f('ceiling_ngn','Planned ceiling (NGN)','money'),f('start_date','Period start (Lagos date)','date'),f('end_date','Period end (Lagos date)','date'),choice('status','Plan status',['draft','active','closed']),f('notes','Assumptions and constraints','textarea')]),
 'budget_line':spec('Budget cost lines','Add an estimate or commitment to a saved budget. Use the finance page for actual expenses.','Updates the budget comparison; cancelled lines are excluded. No money is paid or entered in cash records.',[
  f('budget_id','Budget','reference',ref='budget'),f('name','Cost line'),f('amount_ngn','Planned / committed amount (NGN)','money'),choice('status','Line status',['estimate','committed','cancelled']),f('notes','Basis, quote reference or Unknown','textarea')]),
 'contact':spec('Farm contacts','Keep a minimal local directory of people relevant to field work. Record details only with permission.','Stores contact details locally. No message, invitation or call is sent.',[
  f('name','Name / organisation'),choice('role','Role as reported',['adviser','supplier','buyer','worker','other']),f('contact','Phone / email / address or Unknown'),choice('permission','Permission to store details',['granted','not_recorded']),f('notes','Scope and limitations; avoid private unrelated details','textarea')]),
 'visit':spec('Visits and consultations','Plan a visit with a saved contact; separately record what actually occurred.','Stores a local appointment or report. No person is contacted and no background reminder is sent.',[
  f('contact_id','Contact','reference',ref='contact'),f('name','Visit purpose'),f('due_date','Planned date (Lagos date)','date'),choice('status','Status',['planned','completed','cancelled']),f('performed_at','Actual visit time; required when completed','datetime',False),f('findings','Planned questions or actual findings and limitations','textarea')]),
 'risk':spec('Operational risks','Record a human-assessed operational concern and response owner. This is not a predicted crop diagnosis.','Saves a reported concern and mitigation plan. Closing is user-reported tracking only.',[
  f('name','Concern'),choice('priority','Human-selected priority',['low','routine','prompt']),choice('status','Tracking status',['open','monitoring','closed']),f('owner','Response owner as reported'),f('due_date','Review date (Lagos date)','date'),f('response','Planned response / follow-up findings','textarea')]),
 'milestone':spec('Field milestones','Track a human-selected deliverable separately from crop growth-stage or harvest records.','Saves progress reported by a user; completion does not verify an agricultural outcome.',[
  f('name','Milestone'),f('owner','Owner as reported'),f('due_date','Target / next review date (Lagos date)','date'),choice('status','Progress',['planned','in_progress','blocked','completed','cancelled']),f('evidence','Progress evidence / blocker / uncertainty','textarea')])}
EXAMPLES={
 'supply':{'name':'DEMO: Empty storage sacks','unit':'piece','minimum':'5','storage':'DEMO: Locked store','notes':'Fictional format example; do not save as an actual item.'},
 'movement':{'quantity':'10','reference':'DEMO receipt A','notes':'DEMO: received ten pieces; counted at delivery.'},
 'reservation':{'quantity':'3','purpose':'DEMO: packing work','notes':'DEMO only; issue stock separately when used.'},
 'equipment':{'name':'DEMO: Weighing scale','identifier':'DEMO-SCALE-1','owner':'DEMO custodian','notes':'DEMO: condition not independently inspected.'},
 'maintenance':{'name':'DEMO: Check scale calibration','findings':'DEMO planned scope: qualified person to assess calibration.'},
 'labor':{'name':'DEMO: Store count','worker':'DEMO team','hours':'2','hourly_ngn':'1000','notes':'DEMO: two person-hours, payment not recorded.'},
 'budget':{'name':'DEMO: Packing plan','ceiling_ngn':'20000','notes':'DEMO estimates only; not actual cash.'},
 'budget_line':{'name':'DEMO: Sacks estimate','amount_ngn':'5000','notes':'DEMO supplier quote; not an expense.'},
 'contact':{'name':'DEMO adviser','contact':'Unknown','notes':'DEMO: no verified qualifications or contact details.'},
 'visit':{'name':'DEMO: Discuss crop-season identity','findings':'DEMO planned questions only; no consultation yet.'},
 'risk':{'name':'DEMO: Access road may delay delivery','owner':'DEMO owner','response':'DEMO: check access before arranging transport.'},
 'milestone':{'name':'DEMO: Finish store count','owner':'DEMO owner','evidence':'DEMO planned work; not yet performed.'}}

# Additional workflows share the same append-only resource ledger.
from nexus.farm_app.logistics_catalog import SPECS as LOGISTICS_SPECS, EXAMPLES as LOGISTICS_EXAMPLES
SPECS.update(LOGISTICS_SPECS)
EXAMPLES.update(LOGISTICS_EXAMPLES)

from nexus.farm_app.market_catalog import SPECS as MARKET_SPECS, EXAMPLES as MARKET_EXAMPLES
SPECS.update(MARKET_SPECS)
EXAMPLES.update(MARKET_EXAMPLES)
