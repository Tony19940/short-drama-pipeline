import AppKit
import CoreText
import Foundation
import ImageIO
import UniformTypeIdentifiers

/// Render one line of Khmer/Latin with Core Text (real shaper) to a transparent PNG.
///
///   khmer_coretext --text "សន្តិសុខ" --font KhmerSangamMN --size 64 --color F4C542 --out /tmp/a.png
///   khmer_coretext --batch jobs.json

struct Job: Decodable {
    var text: String
    var font: String
    var size: Double
    var color: String
    var out: String
    var tracking: Double?
}

func hexColor(_ hex: String) -> NSColor {
    var h = hex.trimmingCharacters(in: CharacterSet.alphanumerics.inverted)
    if h.count == 6 { h += "FF" }
    var int: UInt64 = 0
    Scanner(string: h).scanHexInt64(&int)
    let r = CGFloat((int >> 24) & 0xFF) / 255
    let g = CGFloat((int >> 16) & 0xFF) / 255
    let b = CGFloat((int >> 8) & 0xFF) / 255
    let a = CGFloat(int & 0xFF) / 255
    return NSColor(srgbRed: r, green: g, blue: b, alpha: a)
}

func render(_ job: Job) throws {
    let fontName = job.font
    let size = CGFloat(job.size)
    let font = NSFont(name: fontName, size: size)
        ?? NSFont(name: "KhmerSangamMN", size: size)
        ?? NSFont.systemFont(ofSize: size)
    var attrs: [NSAttributedString.Key: Any] = [
        .font: font,
        .foregroundColor: hexColor(job.color),
    ]
    if let tracking = job.tracking {
        attrs[.kern] = CGFloat(tracking)
    }
    let attr = NSAttributedString(string: job.text, attributes: attrs)
    let line = CTLineCreateWithAttributedString(attr)
    var ascent: CGFloat = 0
    var descent: CGFloat = 0
    var leading: CGFloat = 0
    let lineWidth = CTLineGetTypographicBounds(line, &ascent, &descent, &leading)
    let pad: CGFloat = 16
    let scale: CGFloat = 2
    let pw = max(Int(ceil((lineWidth + pad * 2) * scale)), 4)
    let ph = max(Int(ceil((ascent + descent + leading + pad * 2) * scale)), 4)
    let colorSpace = CGColorSpaceCreateDeviceRGB()
    guard let ctx = CGContext(
        data: nil,
        width: pw,
        height: ph,
        bitsPerComponent: 8,
        bytesPerRow: 0,
        space: colorSpace,
        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
    ) else {
        throw NSError(domain: "khmer_coretext", code: 1, userInfo: [NSLocalizedDescriptionKey: "no CGContext"])
    }
    ctx.scaleBy(x: scale, y: scale)
    ctx.clear(CGRect(x: 0, y: 0, width: CGFloat(pw), height: CGFloat(ph)))
    ctx.setShouldAntialias(true)
    ctx.setAllowsAntialiasing(true)
    ctx.textPosition = CGPoint(x: pad, y: pad + descent)
    CTLineDraw(line, ctx)
    guard let cgImage = ctx.makeImage() else {
        throw NSError(domain: "khmer_coretext", code: 2, userInfo: [NSLocalizedDescriptionKey: "no CGImage"])
    }
    let url = URL(fileURLWithPath: job.out) as CFURL
    guard let dest = CGImageDestinationCreateWithURL(url, UTType.png.identifier as CFString, 1, nil) else {
        throw NSError(domain: "khmer_coretext", code: 3, userInfo: [NSLocalizedDescriptionKey: "no dest"])
    }
    CGImageDestinationAddImage(dest, cgImage, nil)
    if !CGImageDestinationFinalize(dest) {
        throw NSError(domain: "khmer_coretext", code: 4, userInfo: [NSLocalizedDescriptionKey: "finalize failed"])
    }
}

func argValue(_ flag: String) -> String? {
    let args = CommandLine.arguments
    guard let i = args.firstIndex(of: flag), i + 1 < args.count else { return nil }
    return args[i + 1]
}

do {
    if let batch = argValue("--batch") {
        let data = try Data(contentsOf: URL(fileURLWithPath: batch))
        let jobs = try JSONDecoder().decode([Job].self, from: data)
        for job in jobs {
            try FileManager.default.createDirectory(
                at: URL(fileURLWithPath: job.out).deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            try render(job)
        }
    } else {
        guard let text = argValue("--text"),
              let out = argValue("--out") else {
            fputs("usage: khmer_coretext --text STR --out PATH [--font NAME] [--size N] [--color RRGGBB]\n", stderr)
            exit(2)
        }
        let job = Job(
            text: text,
            font: argValue("--font") ?? "KhmerSangamMN",
            size: Double(argValue("--size") ?? "64") ?? 64,
            color: argValue("--color") ?? "000000",
            out: out,
            tracking: Double(argValue("--tracking") ?? "")
        )
        try FileManager.default.createDirectory(
            at: URL(fileURLWithPath: out).deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try render(job)
    }
} catch {
    fputs("khmer_coretext: \(error)\n", stderr)
    exit(1)
}
