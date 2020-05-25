    '''
    Implements the quick panel for auto-triggered completions and the
    logic to insert brackets as necessary

    :param edit:
        the current edit

    :param completion_type:
        the completion plugin to use (optional)
        may be:
            * a string indicating the specific completion type, e.g. "cite"
            * a list of such strings
            * None, in which case all available completion types are searched

    :param insert_char:
        the character to insert before the completion; also determines the
        matching brace if any

    :param overwrite:
        boolean indicating whether or not to overwrite the current field;
        if false, text within the current selection or to the left of the
        cursor is treated as the prefix, which usually restricts the
        displayed results;
        if true, the current word will be replaced by the selected entry

    :param force:
        boolean indicating whether or not to match the context or simply
        insert an entry; if force is true, completion_type must be a string;
        if force is true, the bracket matching and word overwriting behaviour
        is disabled
    '''

    NON_WORD_CHARACTERS = u'/\\()"\':,.;<>~!@#$%^&*|+=\\[\\]{}`~?\\s'

    WORD_SEPARATOR_RX = re.compile(
        r'([^' + NON_WORD_CHARACTERS + r']*)',
        re.UNICODE
    )

    def run(
        self, edit, completion_type=None, insert_char="", overwrite=False,
        force=False
    ):
        view = self.view

        for sel in view.sel():
            point = sel.b
            if not view.score_selector(point, "text.tex.latex"):
                self.complete_brackets(view, edit, insert_char)
                return

        # if completion_type is a simple string, try to load it
        if isinstance(completion_type, strbase):
            completion_type = self.get_completion_type(completion_type)
            if completion_type is None:
                if not force:
                    self.complete_brackets(view, edit, insert_char)
                return
        elif force:
            print('Cannot set `force` if completion type is not specified')
            return

        if force:
            insert_char = ''
            overwrite = False

        # tracks any regions to be removed
        remove_regions = []
        prefix = ''

        # handle the _ prefix, if necessary
        if (
            not isinstance(completion_type, FillAllHelper) or
            hasattr(completion_type, 'matches_fancy_prefix')
        ):
            fancy_prefix, remove_regions = self.get_common_fancy_prefix(
                view, view.sel()
            )

        # if we found a _ prefix, we use the raw line, so \ref_eq
        fancy_prefixed_line = None
        if remove_regions:
            fancy_prefixed_line = view.substr(
                getRegion(view.line(point).begin(), point)
            )[::-1]

        # normal line calculation
        line = (view.substr(
            getRegion(view.line(point).begin(), point)
        ) + insert_char)[::-1]

        # handle a list of completion types
        if type(completion_type) is list:
            for name in completion_type:
                try:
                    ct = self.get_completion_type(name)
                    if (
                        fancy_prefixed_line is not None and
                        hasattr(ct, 'matches_fancy_prefix')
                    ):
                        if ct.matches_fancy_prefix(fancy_prefixed_line):
                            completion_type = ct
                            prefix = fancy_prefix
                            break
                        elif ct.matches_line(line):
                            completion_type = ct
                            remove_regions = []
                            break
                    elif ct.matches_line(line):
                        completion_type = ct
                        remove_regions = []
                        break
                except:
                    pass

            if type(completion_type) is list:
                message = "No valid completions found"
                print(message)
                sublime.status_message(message)
                self.complete_brackets(view, edit, insert_char)
                return
        # unknown completion type
        elif (
            completion_type is None or
            not isinstance(completion_type, FillAllHelper)
        ):
            for name in self.get_completion_types():
                ct = self.get_completion_type(name)
                if ct is None:
                    continue

                if (
                    fancy_prefixed_line is not None and
                    hasattr(ct, 'matches_fancy_prefix')
                ):
                    if ct.matches_fancy_prefix(fancy_prefixed_line):
                        completion_type = ct
                        prefix = fancy_prefix
                        break
                    elif ct.matches_line(line):
                        completion_type = ct
                        remove_regions = []
                        break
                elif ct.matches_line(line):
                    completion_type = ct
                    remove_regions = []
                    break

            if (
                completion_type is None or
                isinstance(completion_type, strbase)
            ):
                message = \
                    'Cannot determine completion type for current selection'
                print(message)
                sublime.status_message(message)

                self.complete_brackets(view, edit, insert_char)
                return
        # assume only a single completion type to use
        else:
            # if force is set, we do no matching
            if not force:
                if (
                    fancy_prefixed_line is not None and
                    hasattr(completion_type, 'matches_fancy_prefix')
                ):
                    if completion_type.matches_fancy_prefix(
                        fancy_prefixed_line
                    ):
                        prefix = fancy_prefix
                    elif completion_type.matches_line(line):
                        remove_regions = []
                elif completion_type.matches_line(line):
                    remove_regions = []

        # we only check if the completion type is enabled if we're also
        # inserting a comma or bracket; otherwise, it must've been a keypress
        if insert_char and not completion_type.is_enabled():
            self.complete_brackets(view, edit, insert_char)
            return

        # we are not adding a bracket or comma, we do not have a fancy prefix
        # and the overwrite and force options were not set, so calculate the
        # prefix as the previous word
        if insert_char == '' and not prefix and not overwrite and not force:
            prefix = self.get_common_prefix(view, view.sel())

        # reset the _ completions if we are not using them
        if (
            insert_char and
            "fancy_prefix" in locals() and
            prefix != fancy_prefix
        ):
            remove_regions = []
            prefix = ''

        try:
            completions = completion_type.get_completions(
                view, prefix, line[::-1]
            )
        except:
            self.complete_brackets(
                view, edit, insert_char, remove_regions=remove_regions
            )
            reraise(*sys.exc_info())

        if completions is None:
            self.complete_brackets(
                view, edit, insert_char, remove_regions=remove_regions
            )
            return
        elif type(completions) is tuple:
            formatted_completions, completions = completions
        else:
            formatted_completions = completions

        if len(completions) == 0:
            self.complete_brackets(
                view, edit, insert_char, remove_regions=remove_regions
            )
        elif len(completions) == 1:
            # if there is only one completion and it already matches the
            # current text
            if force:
                view.insert(edit, completions[0])
                return
            else:
                if completions[0] == prefix:
                    return

                if insert_char:
                    insert_text = (
                        insert_char + completions[0]
                        if completions[0] else insert_char
                    )
                    self.insert_at_end(view, edit, insert_text)
                elif completions[0]:
                    self.replace_word(view, edit, completions[0])

                self.complete_auto_match(view, edit, insert_char)
                self.remove_regions(view, edit, remove_regions)
            self.clear_bracket_cache()
        else:
            def on_done(i):
                if i < 0:
                    view.run_command(
                        'latex_tools_fill_all_complete_bracket',
                        {
                            'insert_char': insert_char,
                            'remove_regions':
                                self.regions_to_tuples(remove_regions)
                        }
                    )
                    return

                if force:
                    view.run_command(
                        'insert',
                        {
                            'characters': completions[i]
                        }
                    )
                else:
                    view.run_command(
                        'latex_tools_replace_word',
                        {
                            'insert_char': insert_char,
                            'replacement': completions[i],
                            'remove_regions':
                                self.regions_to_tuples(remove_regions)
                        }
                    )

            view.window().show_quick_panel(formatted_completions, on_done)
            self.clear_bracket_cache()

    def get_common_prefix(self, view, locations):
        '''
        gets the common prefix (if any) from a list of locations

        :param view:
            the current view

        :param locations:
            either a list of points or a list of sublime.Regions
        '''
        if type(locations[0]) is int or type(locations[0]) is long:
            locations = [getRegion(l, l) for l in locations]

        old_prefix = None
        for location in locations:
            if location.empty():
                word_region = getRegion(
                    self.get_current_word(view, location).begin(),
                    location.b
                )
                prefix = view.substr(word_region)
            else:
                prefix = view.substr(location)

            if old_prefix is None:
                old_prefix = prefix
            elif old_prefix != prefix:
                prefix = ''
                break

        return prefix

    def get_current_word(self, view, location):
        '''
        Gets the region containing the current word which contains the caret
        or the given selection.

        The current word is defined between the nearest non-word characters to
        the left and to the right of the current selected location.

        Non-word characters are defined by the WORD_SEPARATOR_RX.

        :param view:
            the current view

        :param location:
            either a point or a sublime.Region that defines the caret position
            or current selection
        '''
        if isinstance(location, sublime.Region):
            start, end = location.begin(), location.end()
        else:
            start = end = location

        start_line = view.line(start)
        end_line = view.line(end)
        # inverse prefix so we search from the right-hand side
        line_prefix = view.substr(getRegion(start_line.begin(), start))[::-1]
        line_suffix = view.substr(getRegion(end, end_line.end()))

        # prefix is the characters before caret
        m = self.WORD_SEPARATOR_RX.search(line_prefix)
        prefix = m.group(1) if m else ''

        m = self.WORD_SEPARATOR_RX.search(line_suffix)
        suffix = m.group(1) if m else ''

        return getRegion(
            start - len(prefix), end + len(suffix)
        )

    def get_completion_types(self):
        '''
        Gets the list of plugin names
        '''
        if self.COMPLETION_TYPES is None:
            self._load_plugins()
        return self.COMPLETION_TYPE_NAMES

    def get_completion_type(self, name):
        if self.COMPLETION_TYPES is None:
            self._load_plugins()
        return self.COMPLETION_TYPES.get(name)

    def insert_at_end(self, view, edit, value):
        '''
        Inserts a string at the end of every current selection

        :param view:
            the current view

        :param edit:
            the current edit

        :param value:
            the string to insert
        '''
        if value:
            new_regions = []
            for sel in view.sel():
                view.insert(edit, sel.end(), value)
                if sel.empty():
                    new_start = new_end = sel.end() + len(value)
                else:
                    new_start = sel.begin()
                    new_end = sel.end() + len(value)

                new_regions.append(getRegion(new_start, new_end))
            self.update_selections(view, new_regions)

    def replace_word(self, view, edit, value):
        '''
        Replaces the current word with the provided string in each selection

        For the definition of word, see get_current_word()

        :param view:
            the current view

        :param edit:
            the current edit

        :param value:
            the string to replace the current word with
        '''
        new_regions = []
        for sel in view.sel():
            if sel.empty():
                word_region = self.get_current_word(view, sel.end())
                start_point = word_region.begin()
                end_point = word_region.end()
            else:
                word_region = self.get_current_word(view, sel)
                start_point = word_region.begin()
                end_point = word_region.end()

            view.replace(
                edit, getRegion(start_point, end_point),
                value
            )

            if sel.empty():
                start_point = end_point = start_point + len(value)
            else:
                end_point = start_point + len(value)
            new_regions.append(getRegion(start_point, end_point))

        self.update_selections(view, new_regions)

    def update_selections(self, view, new_regions):
        '''
        Removes all current selections and adds the specified selections

        NB When calling this method, it is important that all current
        selections be either replaced or simply included as-is. Otherwise,
        these selections will be lost

        :param view:
            the current view

        :param new_regions:
            a list of sublime.Regions that should be selected
        '''
        sel = view.sel()
        sel.clear()
        # we could use ST3's add_all, but this way has less branching...
        for region in new_regions:
            sel.add(region)
