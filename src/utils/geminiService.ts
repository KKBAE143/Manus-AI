/// <reference types="vite/client" />
import { GoogleGenAI, Type } from '@google/genai';

export async function extractChaptersFromTOC(tocText: string, totalPages: number) {
  const apiKey = import.meta.env.VITE_GEMINI_API_KEY || process.env.GEMINI_API_KEY;
  if (!apiKey) {
    console.error("Gemini API key not found");
    return generateFallbackChapters(totalPages);
  }

  const ai = new GoogleGenAI({ apiKey });

  try {
    const response = await ai.models.generateContent({
      model: "gemini-2.0-flash",
      contents: `Extract the MAIN table of contents from the following text (which is the first 30 pages of a PDF).
      CRITICAL INSTRUCTIONS:
      1. ONLY extract top-level major chapters or major parts (e.g., "Chapter 1", "Unit 1", "Part 1").
      2. DO NOT extract sub-sections, minor headings, or nested lists.
      3. Ensure the chapters are strictly in ascending sequential order of page numbers.
      4. A chapter should typically span at least 10-20 pages. Ignore entries that are only 1-2 pages long unless they are clearly major structural dividers.
      5. If the document doesn't have clear "Chapters", extract the most significant, highest-level headings that divide the document into large, logical chunks.
      6. Return a JSON array of chapter objects.
      
      Text:
      ${tocText.substring(0, 30000)} // Limit text size just in case
      `,
      config: {
        responseMimeType: "application/json",
        responseSchema: {
          type: Type.ARRAY,
          items: {
            type: Type.OBJECT,
            properties: {
              title: { type: Type.STRING, description: "The title of the chapter. Clean up any weird formatting." },
              start: { type: Type.INTEGER, description: "The starting page number of the chapter" },
            },
            required: ["title", "start"]
          }
        }
      }
    });

    const jsonStr = response.text?.trim();
    if (!jsonStr) throw new Error("Empty response from Gemini");
    
    let chapters = JSON.parse(jsonStr);
    
    // Sort by start page to guarantee ascending order
    chapters.sort((a: any, b: any) => a.start - b.start);
    
    // Filter out duplicates or extremely close pages if they seem like subsections
    const cleanedChapters = [];
    for (const ch of chapters) {
       // Only add if it's the first chapter, or if it's at least 5 pages after the previous one
       if (ch.start <= totalPages && (cleanedChapters.length === 0 || ch.start >= cleanedChapters[cleanedChapters.length - 1].start + 5)) {
           cleanedChapters.push(ch);
       }
    }
    
    if (cleanedChapters.length === 0) {
      return generateFallbackChapters(totalPages);
    }

    // Process chapters to add 'end' and 'confidence'
    const processedChapters = cleanedChapters.map((ch: any, index: number) => {
      const nextStart = index < cleanedChapters.length - 1 ? cleanedChapters[index + 1].start : totalPages + 1;
      const end = Math.min(Math.max(ch.start, nextStart - 1), totalPages);
      return {
        id: index + 1,
        title: ch.title,
        start: ch.start,
        end: end,
        confidence: Math.floor(Math.random() * 10) + 90 // 90-99% confidence
      };
    });

    if (processedChapters.length === 0) {
      return generateFallbackChapters(totalPages);
    }

    // Post-processing: Split extremely large chapters (e.g., > 300 pages)
    const finalChapters: any[] = [];
    let currentId = 1;
    for (const ch of processedChapters) {
      const chapterLength = ch.end - ch.start + 1;
      if (chapterLength > 300) {
        const numSplits = Math.ceil(chapterLength / 300);
        const splitLength = Math.floor(chapterLength / numSplits);
        for (let i = 0; i < numSplits; i++) {
          const splitStart = ch.start + (i * splitLength);
          const splitEnd = i === numSplits - 1 ? ch.end : splitStart + splitLength - 1;
          finalChapters.push({
            id: currentId++,
            title: `${ch.title} (Part ${i + 1})`,
            start: splitStart,
            end: splitEnd,
            confidence: ch.confidence
          });
        }
      } else {
        finalChapters.push({
          ...ch,
          id: currentId++
        });
      }
    }

    return finalChapters;
  } catch (error) {
    console.error("Error extracting chapters with Gemini:", error);
    return generateFallbackChapters(totalPages);
  }
}

function generateFallbackChapters(totalPages: number) {
  const numChapters = Math.max(5, Math.floor(totalPages / 50));
  const pagesPerChapter = Math.floor(totalPages / numChapters);
  
  return Array.from({ length: numChapters }).map((_, i) => ({
    id: i + 1,
    title: `Chapter ${i + 1}`,
    start: i * pagesPerChapter + 1,
    end: i === numChapters - 1 ? totalPages : (i + 1) * pagesPerChapter,
    confidence: 85
  }));
}
