# Exact OCR (Courier New)

Reads an image and reproduces its text in a fixed-width layout (spacing, columns, blank lines).

    sudo apt-get install tesseract-ocr
    pip install -r requirements.txt
    python exact_ocr.py image.png            # writes image.txt / .html / .docx (Courier New)

Options: `--psm 4` (columns), `--psm 11` (sparse text), `--lang eng`.
