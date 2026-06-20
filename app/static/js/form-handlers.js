// Handle delete form confirmations
document.addEventListener('DOMContentLoaded', function() {
  const deleteForms = document.querySelectorAll('.delete-form');
  
  deleteForms.forEach(form => {
    form.addEventListener('submit', function(e) {
      const confirmMessage = this.dataset.confirm || 'Are you sure?';
      if (!confirm(confirmMessage)) {
        e.preventDefault();
      }
    });
  });
});
