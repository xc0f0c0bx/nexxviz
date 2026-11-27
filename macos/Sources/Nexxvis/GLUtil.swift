import Foundation
import OpenGL.GL3

enum GLUtil {
    static func compile(_ type: GLenum, _ source: String, label: String) -> GLuint? {
        let shader = glCreateShader(type)
        var ok: GLint = 0
        source.withCString { cs in
            var pointer: UnsafePointer<GLchar>? = cs
            glShaderSource(shader, 1, &pointer, nil)
        }
        glCompileShader(shader)
        glGetShaderiv(shader, GLenum(GL_COMPILE_STATUS), &ok)
        if ok == 0 {
            var length: GLint = 0
            glGetShaderiv(shader, GLenum(GL_INFO_LOG_LENGTH), &length)
            var log = [GLchar](repeating: 0, count: Int(max(length, 1)))
            glGetShaderInfoLog(shader, GLsizei(log.count), nil, &log)
            FileHandle.standardError.write(Data("\(label): shader compile failed\n\(String(cString: log))\n".utf8))
            glDeleteShader(shader)
            return nil
        }
        return shader
    }

    static func link(vertex: String, fragment: String, label: String) -> GLuint? {
        guard let vs = compile(GLenum(GL_VERTEX_SHADER), vertex, label: "\(label).vert"),
              let fs = compile(GLenum(GL_FRAGMENT_SHADER), fragment, label: "\(label).frag") else { return nil }
        let program = glCreateProgram()
        glAttachShader(program, vs)
        glAttachShader(program, fs)
        glLinkProgram(program)
        glDeleteShader(vs)
        glDeleteShader(fs)
        var ok: GLint = 0
        glGetProgramiv(program, GLenum(GL_LINK_STATUS), &ok)
        if ok == 0 {
            var length: GLint = 0
            glGetProgramiv(program, GLenum(GL_INFO_LOG_LENGTH), &length)
            var log = [GLchar](repeating: 0, count: Int(max(length, 1)))
            glGetProgramInfoLog(program, GLsizei(log.count), nil, &log)
            FileHandle.standardError.write(Data("\(label): link failed\n\(String(cString: log))\n".utf8))
            glDeleteProgram(program)
            return nil
        }
        return program
    }

    static func makeTexture(width: Int, height: Int, pixels: [UInt8]) -> GLuint {
        var texture: GLuint = 0
        glGenTextures(1, &texture)
        glBindTexture(GLenum(GL_TEXTURE_2D), texture)
        pixels.withUnsafeBytes { raw in
            glTexImage2D(GLenum(GL_TEXTURE_2D), 0, GL_RGBA8, GLsizei(width), GLsizei(height), 0,
                         GLenum(GL_RGBA), GLenum(GL_UNSIGNED_BYTE), raw.baseAddress)
        }
        glTexParameteri(GLenum(GL_TEXTURE_2D), GLenum(GL_TEXTURE_MIN_FILTER), GL_LINEAR)
        glTexParameteri(GLenum(GL_TEXTURE_2D), GLenum(GL_TEXTURE_MAG_FILTER), GL_LINEAR)
        glTexParameteri(GLenum(GL_TEXTURE_2D), GLenum(GL_TEXTURE_WRAP_S), GL_CLAMP_TO_EDGE)
        glTexParameteri(GLenum(GL_TEXTURE_2D), GLenum(GL_TEXTURE_WRAP_T), GL_CLAMP_TO_EDGE)
        return texture
    }

    static func makeEmptyTexture(width: Int, height: Int) -> GLuint {
        var texture: GLuint = 0
        glGenTextures(1, &texture)
        glBindTexture(GLenum(GL_TEXTURE_2D), texture)
        glTexImage2D(GLenum(GL_TEXTURE_2D), 0, GL_RGBA8, GLsizei(width), GLsizei(height), 0,
                     GLenum(GL_RGBA), GLenum(GL_UNSIGNED_BYTE), nil)
        glTexParameteri(GLenum(GL_TEXTURE_2D), GLenum(GL_TEXTURE_MIN_FILTER), GL_LINEAR)
        glTexParameteri(GLenum(GL_TEXTURE_2D), GLenum(GL_TEXTURE_MAG_FILTER), GL_LINEAR)
        glTexParameteri(GLenum(GL_TEXTURE_2D), GLenum(GL_TEXTURE_WRAP_S), GL_CLAMP_TO_EDGE)
        glTexParameteri(GLenum(GL_TEXTURE_2D), GLenum(GL_TEXTURE_WRAP_T), GL_CLAMP_TO_EDGE)
        return texture
    }

    static func upload(_ texture: GLuint, width: Int, height: Int, pixels: [UInt8]) {
        glBindTexture(GLenum(GL_TEXTURE_2D), texture)
        glPixelStorei(GLenum(GL_UNPACK_ALIGNMENT), 1)
        pixels.withUnsafeBytes { raw in
            glTexSubImage2D(GLenum(GL_TEXTURE_2D), 0, 0, 0, GLsizei(width), GLsizei(height),
                            GLenum(GL_RGBA), GLenum(GL_UNSIGNED_BYTE), raw.baseAddress)
        }
        glPixelStorei(GLenum(GL_UNPACK_ALIGNMENT), 4)
    }
}
