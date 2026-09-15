from integrations.marg_hook.nexus_marg_sync import (
    transform_batch_rows,
    transform_product_rows,
    transform_transaction_rows,
)


def test_transform_product_rows_maps_marg_pro_to_nexus_headers():
    rows = [
        {
            "code": "1000000",
            "name": "Crocin 500",
            "product": "Tablet",
            "unit": "PCS",
            "prate": "100.0000",
            "mrp": "150.0000",
        }
    ]

    assert transform_product_rows(rows) == [
        {
            "SKU Code": "1000000",
            "Product Name": "Crocin 500",
            "Category": "Tablet",
            "UOM": "PCS",
            "Unit Cost": "100.0000",
            "Selling Price": "150.0000",
        }
    ]


def test_transform_batch_rows_maps_marg_probat_and_cleans_blank_dates():
    rows = [
        {
            "code": "1000000",
            "batchno": "B001",
            "mfd": "-  -",
            "exp": "31-12-2026",
            "balance": "627.000",
            "godwon": "A",
        }
    ]

    assert transform_batch_rows(rows, default_location="Main") == [
        {
            "SKU Code": "1000000",
            "Batch No": "B001",
            "MFD": "",
            "EXP": "31-12-2026",
            "Quantity": "627.000",
            "Location": "A",
        }
    ]


def test_transform_transaction_rows_maps_marg_dis_to_out_transactions():
    rows = [
        {
            "code": "1000000",
            "vcn": "A000003",
            "date": "31-05-2026",
            "qty": "300.000",
            "rate": "100.0000",
            "godwon": "",
        }
    ]

    assert transform_transaction_rows(rows, default_location="Main") == [
        {
            "SKU Code": "1000000",
            "Location": "Main",
            "Transaction Type": "out",
            "Quantity": "300.000",
            "Unit Cost": "100.0000",
            "Reference No": "A000003",
            "Transaction Date": "31-05-2026",
        }
    ]
