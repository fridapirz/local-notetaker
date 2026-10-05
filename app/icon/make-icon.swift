// Renders the Notetaker app icon (1024×1024 PNG) with Core Graphics.
// Concept: sound becomes notes — a waveform across the top of a note card, text lines below,
// and a coral "recording" dot. Usage: make-icon <out.png>
import AppKit

let size: CGFloat = 1024
let out = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "icon_1024.png"

func rgb(_ hex: UInt32, _ a: CGFloat = 1) -> CGColor {
    CGColor(red: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255,
            blue: CGFloat(hex & 0xFF) / 255, alpha: a)
}

let space = CGColorSpace(name: CGColorSpace.sRGB)!
let ctx = CGContext(data: nil, width: Int(size), height: Int(size), bitsPerComponent: 8, bytesPerRow: 0,
                    space: space, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
// Work in top-left coordinates.
ctx.translateBy(x: 0, y: size)
ctx.scaleBy(x: 1, y: -1)

func linear(_ colors: [CGColor], from: CGPoint, to: CGPoint) {
    let g = CGGradient(colorsSpace: space, colors: colors as CFArray, locations: nil)!
    ctx.drawLinearGradient(g, start: from, end: to, options: [.drawsBeforeStartLocation, .drawsAfterEndLocation])
}

// MARK: Background squircle (macOS icon grid: 824pt body inside 1024 canvas)
let body = CGRect(x: 100, y: 100, width: 824, height: 824)
let bodyPath = CGPath(roundedRect: body, cornerWidth: 186, cornerHeight: 186, transform: nil)

ctx.saveGState()
ctx.setShadow(offset: CGSize(width: 0, height: 14), blur: 34, color: rgb(0x000000, 0.35))
ctx.addPath(bodyPath); ctx.setFillColor(rgb(0x2A2380)); ctx.fillPath()
ctx.restoreGState()

ctx.saveGState()
ctx.addPath(bodyPath); ctx.clip()
linear([rgb(0x7B6CFF), rgb(0x4B3BD6), rgb(0x1F1A5C)], from: CGPoint(x: 260, y: 100), to: CGPoint(x: 760, y: 924))
// soft highlight
let glow = CGGradient(colorsSpace: space, colors: [rgb(0xFFFFFF, 0.28), rgb(0xFFFFFF, 0)] as CFArray, locations: [0, 1])!
ctx.drawRadialGradient(glow, startCenter: CGPoint(x: 330, y: 180), startRadius: 0,
                       endCenter: CGPoint(x: 330, y: 180), endRadius: 560, options: [])
ctx.restoreGState()

// MARK: Note card
let card = CGRect(x: 236, y: 252, width: 552, height: 560)
let cardPath = CGPath(roundedRect: card, cornerWidth: 70, cornerHeight: 70, transform: nil)
ctx.saveGState()
ctx.setShadow(offset: CGSize(width: 0, height: 22), blur: 40, color: rgb(0x0B0830, 0.45))
ctx.addPath(cardPath); ctx.setFillColor(rgb(0xFFFFFF)); ctx.fillPath()
ctx.restoreGState()
ctx.saveGState()
ctx.addPath(cardPath); ctx.clip()
linear([rgb(0xFFFFFF), rgb(0xECEBFF)], from: CGPoint(x: 0, y: card.minY), to: CGPoint(x: 0, y: card.maxY))
ctx.restoreGState()

// MARK: Waveform (violet → pink), tapering at the ends
let heights: [CGFloat] = [34, 70, 128, 92, 176, 120, 214, 150, 186, 98, 140, 66, 36]
let barW: CGFloat = 22, gap: CGFloat = 14
let waveWidth = CGFloat(heights.count) * barW + CGFloat(heights.count - 1) * gap
let waveX = card.midX - waveWidth / 2
let waveMidY: CGFloat = 418
ctx.saveGState()
let bars = CGMutablePath()
for (i, h) in heights.enumerated() {
    let x = waveX + CGFloat(i) * (barW + gap)
    bars.addPath(CGPath(roundedRect: CGRect(x: x, y: waveMidY - h / 2, width: barW, height: h),
                        cornerWidth: barW / 2, cornerHeight: barW / 2, transform: nil))
}
ctx.addPath(bars); ctx.clip()
linear([rgb(0x6D5BFF), rgb(0xA04DF5), rgb(0xFF5C8A)], from: CGPoint(x: waveX, y: 0), to: CGPoint(x: waveX + waveWidth, y: 0))
ctx.restoreGState()

// MARK: Text lines (the notes)
let lineX = waveX
let lines: [(CGFloat, CGFloat, UInt32)] = [  // y, width, color
    (586, waveWidth, 0xB9B4F2),
    (642, waveWidth * 0.78, 0xCAC6F5),
    (698, waveWidth * 0.56, 0xD8D5F8),
]
for (y, w, color) in lines {
    ctx.addPath(CGPath(roundedRect: CGRect(x: lineX, y: y, width: w, height: 26),
                       cornerWidth: 13, cornerHeight: 13, transform: nil))
    ctx.setFillColor(rgb(color)); ctx.fillPath()
}

// MARK: Recording dot on the card's corner
let dot = CGPoint(x: card.maxX - 18, y: card.minY + 18)
ctx.saveGState()
ctx.setShadow(offset: .zero, blur: 36, color: rgb(0xFF4D6D, 0.85))
ctx.addEllipse(in: CGRect(x: dot.x - 60, y: dot.y - 60, width: 120, height: 120))
ctx.setFillColor(rgb(0xFFFFFF)); ctx.fillPath()
ctx.restoreGState()
ctx.saveGState()
ctx.addEllipse(in: CGRect(x: dot.x - 44, y: dot.y - 44, width: 88, height: 88)); ctx.clip()
linear([rgb(0xFF7A7A), rgb(0xF0284A)], from: CGPoint(x: dot.x, y: dot.y - 44), to: CGPoint(x: dot.x, y: dot.y + 44))
ctx.restoreGState()

let image = ctx.makeImage()!
let rep = NSBitmapImageRep(cgImage: image)
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: out))
print(out)
