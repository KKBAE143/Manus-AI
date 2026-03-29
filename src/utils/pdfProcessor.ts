import * as pdfjsLib from 'pdfjs-dist';
// @ts-ignore
import pdfWorker from 'pdfjs-dist/build/pdf.worker.mjs?url';

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorker;

export async function extractPdfMetadata(file: File) {
  const arrayBuffer = await file.arrayBuffer();
  const pdf = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;
  const numPages = pdf.numPages;

  // Extract text from the first 30 pages to find TOC
  let text = '';
  for (let i = 1; i <= Math.min(30, numPages); i++) {
    const page = await pdf.getPage(i);
    const content = await page.getTextContent();
    const pageText = content.items.map((item: any) => item.str).join(' ');
    text += `\n--- Page ${i} ---\n${pageText}`;
  }

  return { numPages, text };
}

export async function extractPdfTextRange(url: string, startPage: number, endPage: number, onProgress?: (progress: number) => void): Promise<string> {
  try {
    const pdf = await pdfjsLib.getDocument(url).promise;
    const totalPages = pdf.numPages;
    
    const actualStart = Math.max(1, startPage);
    const actualEnd = Math.min(totalPages, endPage);
    
    let text = '';
    const totalToProcess = actualEnd - actualStart + 1;
    
    for (let i = actualStart; i <= actualEnd; i++) {
      const page = await pdf.getPage(i);
      const content = await page.getTextContent();
      const pageText = content.items.map((item: any) => item.str).join(' ');
      text += pageText + '\n\n';
      
      if (onProgress) {
        onProgress(Math.round(((i - actualStart + 1) / totalToProcess) * 100));
      }
    }
    
    return text;
  } catch (error) {
    console.error("Error extracting PDF text:", error);
    throw new Error("Failed to extract text from PDF");
  }
}
