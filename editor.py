"""Simple text editor with VIM-like controls.

TODO basic but usable text editor:
    open command
    write command
    handle tabs
    better get_lines method
    handle long lines
    performance testing
"""

import curses
from sys import argv
from contextlib import contextmanager


class Buffer(object):
    """The basic data structure for editable text.

    The buffer is line and row oriented. Line and row numbers start with 0. A
    buffer always has at least one line. All positions within a buffer specify
    a position between characters.

    This class has a minimal public interface that is meant to be wrapped by
    higher-level operations.
    """

    def __init__(self, text=''):
        self._lines = text.split('\n')

    def get_lines(self):
        """Return list of lines in the buffer."""
        # TODO: return variable range of lines
        return list(self._lines) # return a copy

    def _check_point(self, row, col):
        """Raise ValueError if the given row and col are not a valid point."""
        if row < 0 or row > len(self._lines) - 1:
            raise ValueError("Invalid row: '{}'".format(row))
        cur_row = self._lines[row]
        if col < 0 or col > len(cur_row):
            raise ValueError("Invalid col: '{}'".format(col))

    def set_text(self, row1, col1, row2, col2, text):
        """Set the text in the given range.

        The end of the range is exclusive (to allow inserting text without
        removing a single character.

        Example of setting characters 0-3:
         A B C D
        0 1 2 3 4
        |-----|
        """
        self._check_point(row1, col1)
        self._check_point(row2, col2)
        # TODO check that point2 is after or the same as point1

        line = self._lines[row1][:col1] + text + self._lines[row2][col2:]
        self._lines[row1:row2+1] = line.split('\n')


class EditorGUI(object):

    def __init__(self, stdscr, filename):
        self._stdscr = stdscr

        # load file into buffer if given
        if filename is None:
            text = 'This is\na test.'
        else:
            with open(filename) as f:
                text = f.read()

        self._buf = Buffer(text)
        self._row = 0
        self._col = 0
        self._scroll_top = 0 # the first line number in the window
        self._mode = 'normal'
        self._message = ''
        self._will_exit = False

    def _draw_gutter(self, num_start, num_rows, last_line_num):
        """Draw the gutter, and return the gutter width."""
        line_nums = range(num_start, num_start + num_rows)
        assert len(line_nums) == num_rows
        gutter_width = max(3, len(str(last_line_num))) + 1
        for y, line_num in enumerate(line_nums):
            if line_num > last_line_num:
                text = '~'.ljust(gutter_width)
            else:
                text = '{} '.format(line_num).rjust(gutter_width)
            self._stdscr.addstr(y, 0, text, curses.A_REVERSE)
        return gutter_width

    def _draw(self):
        self._stdscr.erase()
        height = self._stdscr.getmaxyx()[0]
        width = self._stdscr.getmaxyx()[1]
        self._draw_status_line(0, height - 1, width)
        self._draw_text(0, 0, width, height - 1)
        self._stdscr.refresh()

    def _draw_status_line(self, left, top, width):
        """Draw the status line."""
        mode = '{} {}'.format(self._mode.upper(),
                              self._message).ljust(width - 1)
        self._stdscr.addstr(top, left, mode, curses.A_REVERSE)
        position = 'LN {}:{} '.format(self._row + 1, self._col + 1)
        self._stdscr.addstr(top, left + width - 1 - len(position), position,
                            curses.A_REVERSE)

    def _get_num_wrapped_lines(self, line_num, width):
        """Return the number of lines the given line number wraps to."""
        return len(self._get_wrapped_lines(line_num, width))

    def _get_wrapped_lines(self, line_num, width):
        """Return the wrapped lines for the given line number."""
        def wrap_text(text, width):
            """Wrap string text into list of strings."""
            if text == '':
                yield ''
            else:
                for i in xrange(0, len(text), width):
                    yield text[i:i + width]
        assert line_num >= 0, 'line_num must be > 0'
        return list(wrap_text(self._buf.get_lines()[line_num], width))

    def _scroll_bottom_to_top(self, bottom, width, height):
        """Return the first visible line's number so bottom line is visible."""
        def verify(top):
            rows = [list(self._get_wrapped_lines(n, width))
                    for n in range(top, bottom + 1)]
            num_rows = sum(len(r) for r in rows)
            assert top <= bottom, ('top line {} may not be below bottom {}'
                                   .format(top, bottom))
            assert num_rows <= height, (
                '{} rows between {} and {}, but only {} remaining. rows are {}'
                .format(num_rows, top, bottom, height, rows))

        top, next_top = bottom, bottom
        # distance in number of lines between top and bottom
        distance = self._get_num_wrapped_lines(bottom, width)

        # move top upwards as far as possible
        while next_top >= 0 and distance <= height:
            top = next_top
            next_top -= 1
            distance += self._get_num_wrapped_lines(max(0, next_top), width)

        verify(top)
        return top

    def _scroll_to(self, line_num, width, row_height):
        """Scroll so the line with the given number is visible."""
        # lowest scroll top that would still keep line_num visible
        lowest_top = self._scroll_bottom_to_top(line_num, width, row_height)

        if line_num < self._scroll_top:
            # scroll up until line_num is visible
            self._scroll_top = line_num
        elif self._scroll_top < lowest_top:
            # scroll down to until line_num is visible
            self._scroll_top = lowest_top


    @staticmethod
    def _wrap_lines(lines, width, max_lines):
        """Wrap list of lines into list of list of lines wrapped to width.

        Returns a list of lists of strings. Each sub-list represents one line
        which has been wrapped over multiple lines at the given width.

        max_lines restricts the total number of lines returned.

        Empty lines are [''].
        """
        def wrap_text(text, width):
            """Wrap string text into list of strings."""
            if text == '':
                yield ''
            else:
                for i in xrange(0, len(text), width):
                    yield text[i:i + width]
        res = []
        lines_remaining = max_lines
        for line in lines:
            wrapped_lines = list(wrap_text(line, width))
            if len(wrapped_lines) <= lines_remaining:
                res.append(wrapped_lines)
                lines_remaining -= len(wrapped_lines)
            else:
                # there's more lines, but can't fit all wrapped lines in
                return res
        # there's no more lines
        return res

    def _draw_text(self, left, top, width, height):
        """Draw the text area."""
        # TODO: handle single lines that occupy the entire window
        highest_line_num = len(self._buf.get_lines())
        gutter_width = max(3, len(str(highest_line_num))) + 1
        line_width = width - gutter_width # width to which text is wrapped
        cursor_y, cursor_x = None, None # where the cursor will be drawn

        # set self._scroll_top so the cursor is visible
        self._scroll_to(self._row, line_width, height)

        # wrapped lines from the top of the screen
        unwrapped_lines = self._buf.get_lines()[self._scroll_top:]
        wrapped_lines = self._wrap_lines(unwrapped_lines, line_width, height)
        numbered_wrapped_lines = list(enumerate(wrapped_lines,
                                                self._scroll_top))
        drawable_rows = range(top, top + height)

        current_y = top
        for num, logical_line in numbered_wrapped_lines:
            # calculate cursor position if cursor must be on this line
            if num == self._row:
                cursor_y = current_y + self._col / line_width
                cursor_x = left + gutter_width + self._col % line_width
            # draw the gutter and first line
            gutter = '{} '.format(num + 1).rjust(gutter_width)
            self._stdscr.addstr(current_y, left, gutter, curses.A_REVERSE)
            self._stdscr.addstr(current_y, left + len(gutter), logical_line[0])
            current_y += 1
            # draw wrapped lines, if any
            for wrapped_line in logical_line[1:]:
                gutter = ' ' * gutter_width
                self._stdscr.addstr(current_y, left, gutter, curses.A_REVERSE)
                self._stdscr.addstr(current_y, left + len(gutter), wrapped_line)
                current_y += 1

        # TODO draw @ for incomplete wrapped lines

        self._bottom_line_num = numbered_wrapped_lines[-1][0]

        # draw gutter for empty lines (without reverse colour)
        empty_lines = range(current_y, top + height)
        self._bottom_line_num += len(empty_lines)
        for _ in empty_lines:
            gutter = '~'.ljust(gutter_width)
            self._stdscr.addstr(current_y, left, gutter)
            current_y += 1

        # position the cursor
        # TODO: scrolling down to wrapped line hits this
        assert cursor_x != None and cursor_y != None, (
                "Could not place cursor on line {}, lines {} to {} are shown"
                .format(self._row, self._scroll_top, self._bottom_line_num))
        self._stdscr.move(cursor_y + 0, cursor_x + 0)

    def _handle_normal_keypress(self, char):
        if char == ord('q'): # quit
            self._will_exit = True
        elif char == ord('j'): # down
            self._row += 1
        elif char == ord('k'): # up
            self._row -= 1
        elif char == ord('h'): # left
            self._col -= 1
        elif char == ord('l'): # right
            self._col += 1
        elif char == ord('0'): # move to beginning of line
            self._col = 0
        elif char == ord('$'): # move to end of line
            cur_line_len = len(self._buf.get_lines()[self._row])
            self._col = cur_line_len - 1
        elif char == ord('x'):
            self._buf.set_text(self._row, self._col, self._row,
                                self._col + 1, '')
        elif char == ord('i'):
            self._mode = "insert"
        elif char == ord('a'):
            self._mode = "insert"
            self._col += 1
        elif char == ord('o'): # insert line after current
            cur_line_len = len(self._buf.get_lines()[self._row])
            self._buf.set_text(self._row, cur_line_len, self._row, cur_line_len, '\n')
            self._row += 1
            self._col = 0
            self._mode = "insert"
        elif char == ord('O'): # insert line before current
            self._buf.set_text(self._row, 0, self._row, 0, '\n')
            self._col = 0
            self._mode = "insert"
        else:
            self._message = 'Unknown key: {}'.format(char)

    def _handle_insert_keypress(self, char):
        if char == 27:
            # leaving insert mode moves cursor left
            if self._mode == 'insert':
                self._col -= 1
            self._mode = "normal"
        elif char == 127: # backspace
            if self._col == 0 and self._row == 0:
                pass # no effect
            elif self._col == 0:
                # join the current line with the previous one
                prev_line = self._buf.get_lines()[self._row - 1]
                cur_line = self._buf.get_lines()[self._row]
                self._buf.set_text(self._row - 1, 0, self._row,
                                    len(cur_line), prev_line + cur_line)
                self._col = len(prev_line)
                self._row -= 1
            else:
                # remove the previous character
                self._buf.set_text(self._row, self._col - 1, self._row,
                                    self._col, '')
                self._col -= 1
        else:
            self._message = 'inserted {} at row {} col {}'.format(char, self._row, self._col)
            self._buf.set_text(self._row, self._col, self._row,
                                self._col, chr(char))
            if chr(char) == '\n':
                self._row += 1
                self._col = 0
            else:
                self._col += 1

    def main(self):
        while not self._will_exit:
            self._draw()
            self._message = ''

            char = self._stdscr.getch()
            if self._mode == 'normal':
                self._handle_normal_keypress(char)
            elif self._mode == 'insert':
                self._handle_insert_keypress(char)

            # TODO: get rid of this position clipping
            num_lines = len(self._buf.get_lines())
            self._row = min(num_lines - 1, max(0, self._row))
            # on empty lines, still allow col 1
            num_cols = max(1, len(self._buf.get_lines()[self._row]))
            # in insert mode, allow using append after the last char
            if self._mode == 'insert':
                num_cols += 1
            self._col = min(num_cols - 1, max(0, self._col))


@contextmanager
def use_curses():
    stdscr = curses.initscr()
    curses.noecho() # do not echo keys
    curses.cbreak() # don't wait for enter
    try:
        yield stdscr
    finally:
        # clean up and exit
        curses.nocbreak()
        stdscr.keypad(0)
        curses.echo()
        curses.endwin()


def curses_main():
    filename = argv[1] if len(argv) > 1 else None
    with use_curses() as stdscr:
        gui = EditorGUI(stdscr, filename)
        gui.main()
    print gui._buf.get_lines()


if __name__ == '__main__':
    curses_main()
