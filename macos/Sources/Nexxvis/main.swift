import AppKit

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var window: NSWindow?

    func applicationDidFinishLaunching(_ notification: Notification) {
        let rect = NSRect(x: 0, y: 0, width: 1280, height: 720)
        let window = NSWindow(contentRect: rect,
                              styleMask: [.titled, .closable, .miniaturizable, .resizable],
                              backing: .buffered, defer: false)
        window.title = "Nexxvis"
        window.center()
        window.contentView = VizView(viewFrame: rect)
        window.makeKeyAndOrderFront(nil)
        self.window = window
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

// Headless snapshot mode, used for verification without a display.
let arguments = CommandLine.arguments
if let index = arguments.firstIndex(of: "--snapshot"), index + 1 < arguments.count {
    let path = arguments[index + 1]
    var time = 129.5
    if let i = arguments.firstIndex(of: "--time"), i + 1 < arguments.count,
       let v = Double(arguments[i + 1]) { time = v }
    var width = 2560
    var height = 1440
    if let i = arguments.firstIndex(of: "--width"), i + 1 < arguments.count,
       let v = Int(arguments[i + 1]) { width = v }
    if let i = arguments.firstIndex(of: "--height"), i + 1 < arguments.count,
       let v = Int(arguments[i + 1]) { height = v }
    do {
        try Snapshot.run(path: path, time: time, width: width, height: height)
        exit(0)
    } catch {
        FileHandle.standardError.write(Data("snapshot failed: \(error)\n".utf8))
        exit(1)
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.regular)
let delegate = AppDelegate()
app.delegate = delegate

let mainMenu = NSMenu()
let appMenuItem = NSMenuItem()
mainMenu.addItem(appMenuItem)
let appMenu = NSMenu()
appMenu.addItem(withTitle: "About Nexxvis",
                action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)),
                keyEquivalent: "")
appMenu.addItem(NSMenuItem.separator())
appMenu.addItem(withTitle: "Hide Nexxvis", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
appMenu.addItem(NSMenuItem.separator())
appMenu.addItem(withTitle: "Quit Nexxvis", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
appMenuItem.submenu = appMenu

let viewMenuItem = NSMenuItem()
mainMenu.addItem(viewMenuItem)
let viewMenu = NSMenu(title: "View")
let fullScreenItem = NSMenuItem(title: "Enter Full Screen",
                                action: #selector(NSWindow.toggleFullScreen(_:)),
                                keyEquivalent: "f")
fullScreenItem.keyEquivalentModifierMask = [.command, .control]
viewMenu.addItem(fullScreenItem)
viewMenuItem.submenu = viewMenu
app.mainMenu = mainMenu

app.run()
