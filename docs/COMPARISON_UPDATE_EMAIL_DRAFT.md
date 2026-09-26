Subject: Benchmark comparison updates and demo walkthrough

Hi Nikitha,

I have prepared the requested updates for review:

| Area | Updated behaviour |
|---|---|
| Headings | Full names are visible: Insurer Third Party invoices and EXL/ In house Benchmark invoices. |
| Upload documents | Shows upload controls and the processing receipt for that source. |
| Document intelligence | Starts at Mapping review and includes the invoice and assessment details below it. |
| Separate sources | Third-party, in-house and new invoices stay separate. Only the first two contribute to their own benchmarks. |
| Comparison | Shows Third-party P90, In-house P90 and the new invoice item price side by side. |
| Challenge | Uses 50% of each P90. Both benchmarks are needed. The existing 10% and GBP 5 thresholds apply to the combined price. |
| Email draft | Includes the selected items, both P90s, proposed prices and total reduction. It does not send automatically. |

The synthetic demo pack contains three invoice/assessment pairs for each source, with expected results and upload instructions. The three new invoices produce total reductions of GBP 58.80, GBP 78.00 and GBP 93.00 in an empty demo claim.

The code was tested locally using the real upload API and browser. Please review the updated build with your original documents before treating it as verified on your computer.

I followed the written requirements and screenshots. I have not received the recording yet, so any additional points from it still need to be checked.

Thanks,
Varun
