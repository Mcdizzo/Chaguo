const subjectsList = document.getElementById('subjectsList');
const addSubjectBtn = document.getElementById('addSubjectBtn');
const findBtn = document.getElementById('findBtn');
const backBtn = document.getElementById('backBtn');
const inputSection = document.getElementById('inputSection');
const resultsSection = document.getElementById('resultsSection');
const resultsGrid = document.getElementById('resultsGrid');
const resultsTitle = document.getElementById('resultsTitle');
const resultsSearchInput = document.getElementById('resultsSearchInput');
const searchHint = document.getElementById('searchHint');
const searchModeRadios = document.querySelectorAll('input[name="searchMode"]');
const template = document.getElementById('subjectRowTemplate');

let allResults = [];
let searchMode = 'university';

const SEARCH_PLACEHOLDERS = {
  university: 'Search by university name…',
  program: 'Search by program name…',
};

function addSubjectRow() {
  const clone = template.content.cloneNode(true);
  const row = clone.querySelector('.subject-row');
  const removeBtn = row.querySelector('.remove-btn');

  removeBtn.addEventListener('click', () => {
    row.style.opacity = '0';
    row.style.transform = 'translateY(-8px)';
    row.style.transition = 'opacity 0.2s, transform 0.2s';
    setTimeout(() => row.remove(), 200);
  });

  subjectsList.appendChild(clone);
}

function getSubjects() {
  const rows = subjectsList.querySelectorAll('.subject-row');
  const subjects = [];
  rows.forEach(row => {
    const subject = row.querySelector('.subject-input').value.trim();
    const grade = row.querySelector('.grade-select').value;
    const level = row.querySelector('.level-select').value;
    if (subject && grade) {
      subjects.push({ subject, grade, level });
    }
  });
  return subjects;
}

function renderCard(prog, index) {
  const card = document.createElement('div');
  card.className = 'program-card';
  card.style.animationDelay = `${index * 0.05}s`;

  const marginLabel = prog.margin > 0
    ? `+${prog.margin.toFixed(1)} pts above minimum`
    : 'Exactly at minimum';

  const websiteLink = prog.university_website
    ? `<a href="${prog.university_website.startsWith('http') ? prog.university_website : 'https://' + prog.university_website}" target="_blank" rel="noopener" class="uni-link">Visit University →</a>`
    : '';

  const capacity = prog.admission_capacity
    ? `${prog.admission_capacity} spots`
    : 'N/A';

  const duration = prog.duration_years
    ? `${prog.duration_years} yrs`
    : 'N/A';

  const minPts = prog.minimum_points !== null
    ? `Min ${prog.minimum_points} pts`
    : 'No minimum listed';

  const requirements = prog.requirements_raw
    ? `<p class="requirements-text">${prog.requirements_raw}</p>`
    : '';

  card.innerHTML = `
    <div class="card-top">
      <div class="program-name">${prog.program_name}</div>
      <div class="margin-badge">${marginLabel}</div>
    </div>
    <div class="university-name">${prog.university_name} · ${prog.location || ''}</div>
    <div class="card-meta">
      <span class="meta-chip">${minPts}</span>
      <span class="meta-chip">${capacity}</span>
      <span class="meta-chip">${duration}</span>
      ${prog.program_code ? `<span class="meta-chip">${prog.program_code}</span>` : ''}
    </div>
    ${requirements}
    <div class="card-footer">
      ${websiteLink}
    </div>
  `;

  return card;
}

function matchesSearch(prog, query) {
  if (!query) return true;
  const haystack = searchMode === 'university'
    ? (prog.university_name || '')
    : (prog.program_name || '');
  return haystack.toLowerCase().includes(query);
}

function getFilteredResults() {
  const query = resultsSearchInput.value.trim().toLowerCase();
  return allResults.filter(prog => matchesSearch(prog, query));
}

function updateSearchHint(filteredCount, query) {
  if (!query) {
    searchHint.textContent = '';
    return;
  }

  if (filteredCount === 0) {
    if (searchMode === 'university') {
      searchHint.textContent = 'No matching university in your qualified programs.';
    } else {
      searchHint.textContent = 'No matching program in your results.';
    }
    searchHint.classList.add('no-match');
    return;
  }

  searchHint.classList.remove('no-match');
  const noun = searchMode === 'university' ? 'universities' : 'programs';
  searchHint.textContent = `Showing ${filteredCount} of ${allResults.length} ${noun}.`;
}

function renderResultsList() {
  const filtered = getFilteredResults();
  const query = resultsSearchInput.value.trim();

  resultsGrid.innerHTML = '';

  if (allResults.length === 0) {
    resultsGrid.innerHTML = `
      <div class="empty-state">
        <h3>No programs found</h3>
        <p>Try adjusting your grades or adding more subjects.</p>
      </div>
    `;
    resultsTitle.textContent = 'Programs you qualify for';
    updateSearchHint(0, query);
    return;
  }

  const total = allResults.length;
  const showing = filtered.length;

  if (query) {
    resultsTitle.textContent = `${showing} of ${total} program${total !== 1 ? 's' : ''} matching your search`;
  } else {
    resultsTitle.textContent = `${total} program${total !== 1 ? 's' : ''} you qualify for`;
  }

  if (showing === 0) {
    resultsGrid.innerHTML = `
      <div class="empty-state">
        <h3>No matches</h3>
        <p>Try a different spelling or switch search mode.</p>
      </div>
    `;
  } else {
    filtered.forEach((prog, i) => {
      resultsGrid.appendChild(renderCard(prog, i));
    });
  }

  updateSearchHint(showing, query);
}

function setSearchMode(mode) {
  searchMode = mode;
  resultsSearchInput.placeholder = SEARCH_PLACEHOLDERS[mode];
  renderResultsList();
}

function resetResultsView() {
  allResults = [];
  resultsSearchInput.value = '';
  searchMode = 'university';
  searchModeRadios.forEach(radio => {
    radio.checked = radio.value === 'university';
  });
  resultsSearchInput.placeholder = SEARCH_PLACEHOLDERS.university;
  searchHint.textContent = '';
  searchHint.classList.remove('no-match');
}

async function findPrograms() {
  const subjects = getSubjects();

  if (subjects.length === 0) {
    alert('Please add at least one subject with a grade.');
    return;
  }

  findBtn.textContent = 'Searching...';
  findBtn.disabled = true;

  try {
    const response = await fetch('/match', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ subjects }),
    });

    const data = await response.json();

    if (data.error) {
      alert(data.error);
      return;
    }

    allResults = data.results || [];
    resultsSearchInput.value = '';
    searchMode = 'university';
    searchModeRadios.forEach(radio => {
      radio.checked = radio.value === 'university';
    });
    resultsSearchInput.placeholder = SEARCH_PLACEHOLDERS.university;
    searchHint.textContent = '';
    searchHint.classList.remove('no-match');
    renderResultsList();

    inputSection.classList.add('hidden');
    resultsSection.classList.remove('hidden');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  } catch (err) {
    alert('Something went wrong. Please try again.');
    console.error(err);
  } finally {
    findBtn.textContent = 'Find My Programs';
    findBtn.disabled = false;
  }
}

addSubjectBtn.addEventListener('click', addSubjectRow);
findBtn.addEventListener('click', findPrograms);
backBtn.addEventListener('click', () => {
  resultsSection.classList.add('hidden');
  inputSection.classList.remove('hidden');
  resetResultsView();
  resultsGrid.innerHTML = '';
  window.scrollTo({ top: 0, behavior: 'smooth' });
});

resultsSearchInput.addEventListener('input', renderResultsList);

searchModeRadios.forEach(radio => {
  radio.addEventListener('change', () => {
    if (radio.checked) setSearchMode(radio.value);
  });
});

addSubjectRow();
addSubjectRow();
