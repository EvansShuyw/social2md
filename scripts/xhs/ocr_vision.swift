import Foundation
import Vision
import AppKit

// Batch local OCR via Apple Vision framework. Supports Simplified Chinese.
// Usage: ocr_vision.swift <image1> <image2> ...
// Prints a delimited block per image so Python can parse it.

let args = CommandLine.arguments
guard args.count > 1 else {
    fputs("Usage: ocr_vision.swift <image>...\n", stderr)
    exit(1)
}

let separator = "<<<XHS_OCR_IMAGE>>>"

for (idx, path) in args.dropFirst().enumerated() {
    if idx > 0 { print(separator) }
    print("@@PATH@@\(path)")
    guard let img = NSImage(contentsOfFile: path),
          let cgImage = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
        print("@@ERROR@@LOAD_FAILED")
        continue
    }
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = true
    // Prefer Simplified Chinese + English; fall back if language unsupported.
    request.recognitionLanguages = ["zh-Hans", "en-US"]

    let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
    do {
        try handler.perform([request])
        let observations = request.results ?? []
        if observations.isEmpty {
            print("@@EMPTY@@1")
        } else {
            // Vision returns top-to-bottom, left-to-right already.
            for obs in observations {
                if let candidate = obs.topCandidates(1).first {
                    print(candidate.string)
                }
            }
        }
    } catch {
        print("@@ERROR@@\(error.localizedDescription)")
    }
}
