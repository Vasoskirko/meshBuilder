"""Section geometry: selection."""


def deselect_rod(self):
    """Снимает выделение со стержня."""
    self.active_rod_coord = None


def clear_all_selection(self):
    """Сбрасывает выбор подканалов и снимает выделение со стержня."""
    self.selected_subchannels.clear()
    self.active_rod_coord = None
    self.active_sub_id = None


def select_all_subchannels(self):
    self.selected_subchannels = set(self.subchannels.keys())
    self.active_sub_id = None


def select_subchannel(self, sub_id):
    if sub_id not in self.subchannels:raise ValueError('Подканал отсутствует в текущей геометрии')
    if sub_id in self.selected_subchannels:
        self.selected_subchannels.remove(sub_id)
    else:
        self.selected_subchannels.add(sub_id)
    self.active_sub_id = sub_id


def add_subchannel(self, sub_id):
    if sub_id not in self.subchannels:raise ValueError('Подканал отсутствует в текущей геометрии')
    self.selected_subchannels.add(sub_id)
    self.active_sub_id = sub_id


def remove_subchannel(self, sub_id):
    self.selected_subchannels.discard(sub_id)
    if self.active_sub_id == sub_id:
        self.active_sub_id = None


def get_candidate_neighbors(self):
    if not self.selected_subchannels:
        return set()
    candidates = set()
    for sub_id in self.selected_subchannels:
        sub = self.subchannels[sub_id]
        for n_id in sub.neighbor_sub_ids:
            if n_id not in self.selected_subchannels:
                candidates.add(n_id)
    return candidates


def get_selection_summary(self):
    return self._calc_summary_for_ids(self.selected_subchannels)


def get_total_assembly_summary(self):
    return self._calc_summary_for_ids(self.subchannels.keys())
