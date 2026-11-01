# NEXUS Produce & Market — 50 upgrades

New feature phase: post-harvest market records. These are specific workflow, calculation, reporting and guidance capabilities, not 50 independent applications.

1. **Produce & Market workspace** — New /market page brings produce, buyer interest, order and receipt records together with the existing project branding.

2. **Produce lot register** — Identify distinct lots in kilograms, with crop and storage details.

3. **Optional established harvest links** — Only actual lots can link existing same-field harvests; test lots leave this optional association blank.

4. **Frozen harvest copies** — Preserve harvest details at the time of association.

5. **Initial harvest assignment guard** — Initial quantities assigned to linked lots cannot exceed their frozen harvest quantity. This does not verify that lots are physically distinct.

6. **Harvest drift checks** — Flag a changed or missing current harvest without rewriting the lot association.

7. **Lot availability status** — Record available, hold or closed, with history.

8. **Produce weighing corrections** — Signed, nonzero changes affect this market ledger only.

9. **Condition-check records** — Record actual inspection time, sample method and user-reported findings without claiming quality certification.

10. **Local offer drafts** — Prepare title, per-kilogram asking price, terms and optional validity date.

11. **Offer status and validity** — Track open, paused, withdrawn and reported validity without publishing anything.

12. **Manual offer sheets** — Download a branded HTML or JSON offer copy with recorded quantity, source and limitations; no buyer is contacted.

13. **Buyer enquiry records** — Link a contact, lot, requested quantity and requested date.

14. **Enquiry response history** — Track new, responded or closed with notes and retained earlier versions.

15. **Sales-order drafts** — Record a buyer, agreement date, planned delivery date and agreed terms.

16. **Draft planning without reservations** — Draft orders do not reserve stock.

17. **Order lines** — Associate each quantity and agreed price with a produce lot.

18. **Line cancellation history** — Cancel unfulfilled unused lines without erasing them. Lines with delivery evidence are retained.

19. **Decimal order values** — Calculate per-line values with half-up kobo rounding, then sum current active lines.

20. **Explicit order confirmation** — Require active lines before confirming an order.

21. **Confirmed quantity commitments** — Reserve outstanding quantities in the separate market ledger.

22. **Overbooking prevention** — Reject new confirmations or commitment increases that exceed recorded quantities, including simultaneous saves.

23. **Commitment shortfall display** — Record truthful losses/returns even when existing commitments become short; show shortfall instead of inventing stock.

24. **Actual delivery records** — Link delivered kilograms, time and evidence reference to an order line.

25. **Market quantity deduction** — Deliveries reduce market lot balances only; no core-stock movement or Finance sale is created.

26. **Partial delivery visibility** — Show no delivery, part recorded or all current quantity recorded without claiming verification.

27. **Ordered-quantity guard** — Net deliveries cannot exceed the current ordered quantity.

28. **Held-lot workflow guard** — Held/closed lots cannot be newly committed or used for new delivery entries until availability is deliberately reviewed.

29. **Agreement chronology checks** — Delivery and payment times cannot predate actual agreement; returns cannot predate delivery.

30. **Price/reference preservation** — After delivery/payment evidence, a line retains its order, lot and unit price. New terms need a separate supported record.

31. **Customer receipt records** — Record actual user-reported receipts, amounts, times and references without transferring money.

32. **Customer refund records** — Record actual refunds separately; no automatic refund is generated.

33. **Net receipt calculation** — Calculate receipts minus refunds in decimal arithmetic.

34. **Unreceived-value display** — Show current order value minus net receipts; this is not an audited debt figure.

35. **Receipt/refund bounds** — Prevent net receipts below zero or above current order value, and refunds before sufficient reported receipts.

36. **Produce return records** — Associate returned kilograms and time with their original delivery.

37. **Restocked returns** — Only explicitly restocked quantities add back to available market-lot stock.

38. **Quarantine and discard separation** — Keep quarantined/discarded returns out of market availability and show their quantities separately.

39. **Return quantity guard** — Total returns cannot exceed the original delivered quantity.

40. **Replacement delivery support** — A returned quantity can be delivered again while respecting net ordered-quantity bounds and stock.

41. **Order closure without success claims** — Close tracking and release remaining commitments while preserving undelivered quantities and history.

42. **Transport estimates** — Link carrier contacts and quotes to orders without changing order value or recording an expense.

43. **Order follow-up notes** — Record owners, future review dates and open/closed status without sending messages or reminders.

44. **Order statements** — Download dated HTML or JSON copies of current orders, lines, delivery/return records and receipts; not tax or authenticated invoices.

45. **Statement privacy scope** — Copy the buyer name but not the contact directory phone/email fields into statements. Free text still needs human review before sharing.

46. **Actual/test market separation** — Reuse source and field guards, with tests excluded by default from actual-record reports.

47. **Market-specific filters and exports** — Filter market entries by field, source, literal text, status and history; market JSON excludes unrelated resource report sections.

48. **Market dates in manual calendar** — Active dated orders, enquiries and follow-ups join calendar copies in the chosen market field/source scope.

49. **Guides and examples** — Add all 12 new form guides plus an overview guide, with meanings, save effects, prerequisites and fictional examples.

50. **Existing safety and evidence integration** — New records use append-only corrections, stale-save checks, retry reuse, hash/relationship checks and full SQLite backups; explicit case links can freeze selected market records without changing older bundles.

