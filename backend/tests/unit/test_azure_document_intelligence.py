from app.extraction.azure_document_intelligence import AzureDocumentIntelligenceOCR


def test_azure_word_coordinates_scale_into_existing_source_viewer_space() -> None:
    word = AzureDocumentIntelligenceOCR._word(
        {
            "content": "Windscreen",
            "confidence": 0.97,
            "polygon": [1, 2, 3, 2, 3, 4, 1, 4],
        },
        source_width=10,
        source_height=10,
        target_width=100,
        target_height=200,
    )

    assert word is not None
    assert word.text == "Windscreen"
    assert word.confidence == 0.97
    assert word.bbox.model_dump() == {
        "x0": 10.0,
        "y0": 40.0,
        "x1": 30.0,
        "y1": 80.0,
    }
