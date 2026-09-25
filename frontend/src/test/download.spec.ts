import { describe, expect, it, vi } from 'vitest'
import { downloadBlob, sanitizeDownloadFilename } from '../lib/download'

describe('sanitizeDownloadFilename', () => {
  it('清洗文件名中的非法字符', () => {
    expect(sanitizeDownloadFilename('backup/file:test*.tar.gz')).toBe('backup_file_test_.tar.gz')
    expect(sanitizeDownloadFilename('name<with>special|chars?.csv')).toBe('name_with_special_chars_.csv')
  })

  it('空值或纯特殊符号使用 fallback', () => {
    expect(sanitizeDownloadFilename('')).toBe('download')
    expect(sanitizeDownloadFilename(null, 'default_name')).toBe('default_name')
    expect(sanitizeDownloadFilename(undefined)).toBe('download')
    expect(sanitizeDownloadFilename('   ', 'backup')).toBe('backup')
  })

  it('剥离控制字符（含 NUL）', () => {
    expect(sanitizeDownloadFilename('back\u0000up.tar.gz')).toBe('backup.tar.gz')
    expect(sanitizeDownloadFilename('we\u001bbird.txt')).toBe('webird.txt')
    expect(sanitizeDownloadFilename('a\u007fb.csv')).toBe('ab.csv')
    // 剥离后为空时回退 fallback
    expect(sanitizeDownloadFilename('\u0000\u001f\u007f')).toBe('download')
  })

  it('剥离首尾点与空格', () => {
    expect(sanitizeDownloadFilename('  spaced.txt  ')).toBe('spaced.txt')
    expect(sanitizeDownloadFilename('...dotted...')).toBe('dotted')
    expect(sanitizeDownloadFilename('. .')).toBe('download')
  })

  it('Windows 保留名加下划线前缀', () => {
    expect(sanitizeDownloadFilename('CON')).toBe('_CON')
    expect(sanitizeDownloadFilename('con.txt')).toBe('_con.txt')
    expect(sanitizeDownloadFilename('PRN.tar.gz')).toBe('_PRN.tar.gz')
    expect(sanitizeDownloadFilename('com3')).toBe('_com3')
    expect(sanitizeDownloadFilename('lpt9.log')).toBe('_lpt9.log')
    expect(sanitizeDownloadFilename('aux')).toBe('_aux')
    expect(sanitizeDownloadFilename('nul.csv')).toBe('_nul.csv')
    // 普通同名文件不受影响
    expect(sanitizeDownloadFilename('console.txt')).toBe('console.txt')
    expect(sanitizeDownloadFilename('com')).toBe('com')
    expect(sanitizeDownloadFilename('lpt')).toBe('lpt')
  })
})

describe('downloadBlob', () => {
  it('创建下载链接并触发点击与清理', () => {
    const blob = new Blob(['test content'], { type: 'text/plain' })
    const createObjectURL = vi.fn().mockReturnValue('blob:http://localhost/test-uuid')
    const revokeObjectURL = vi.fn()
    window.URL.createObjectURL = createObjectURL
    window.URL.revokeObjectURL = revokeObjectURL

    const appendSpy = vi.spyOn(document.body, 'appendChild')

    downloadBlob(blob, 'unsafe/file:name.txt')

    expect(createObjectURL).toHaveBeenCalledWith(blob)
    expect(appendSpy).toHaveBeenCalled()

    const appendedAnchor = appendSpy.mock.calls[0][0] as HTMLAnchorElement
    expect(appendedAnchor.download).toBe('unsafe_file_name.txt')
    expect(appendedAnchor.href).toBe('blob:http://localhost/test-uuid')
    expect(appendedAnchor.style.display).toBe('none')

    // 验证已被移除
    expect(document.body.contains(appendedAnchor)).toBe(false)
  })
})
